"""Home Connect Coordinator."""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from typing import TYPE_CHECKING

from homeassistant.const import CONF_DESCRIPTION, CONF_DEVICE_ID, CONF_HOST
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeconnect_websocket import (
    AllreadyConnectedError,
    ConnectionFailedError,
    ConnectionState,
    HCHandshakeError,
    HomeAppliance,
)

from .const import (
    CONF_AES_IV,
    CONF_PSK,
    INITIAL_CONNECT_BACKOFF,
    MAX_CONNECT_BACKOFF,
    MAX_RECONECT_TIME,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import HCConfigEntry

_LOGGER = logging.getLogger(__name__)


class HomeConnectCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    config_entry: HCConfigEntry
    appliance: HomeAppliance
    _connecting: bool = True
    _reconnecting: bool = False
    _reconnect_timer: asyncio.TimerHandle | None = None
    connected: bool = False

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: HCConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=config_entry.data["description"]["info"]["vib"],
            config_entry=config_entry,
            always_update=True,
        )
        self.appliance = HomeAppliance(
            description=deepcopy(config_entry.data[CONF_DESCRIPTION]),
            host=config_entry.data[CONF_HOST],
            app_name="Homeassistant",
            app_id=config_entry.data[CONF_DEVICE_ID],
            psk64=config_entry.data[CONF_PSK],
            iv64=config_entry.data.get(CONF_AES_IV, None),
            connection_callback=self._connection_state_callback,
        )
        self.disconnect_time = time.time()
        if not self.appliance.info:
            msg = "Appliance has no device info"
            raise ConfigEntryError(msg)

    async def close(self) -> None:
        self._connecting = False
        self._cancel_reconnect_timer()
        await self.appliance.close()

    async def _async_setup(self) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self._connect(), f"homeconnect_ws_{self.name}"
        )

    async def _connect(self) -> None:
        self.logger.debug(
            "Connecting to %s", self.config_entry.data[CONF_DESCRIPTION]["info"].get("vib")
        )
        first_failure = True
        backoff = INITIAL_CONNECT_BACKOFF
        while self._connecting:
            try:
                await self.appliance.connect()
                if self.appliance.session.connected:
                    self.connected = True  # FIX
                    self.async_set_updated_data(None)  # FIX
                    return
            except ConnectionFailedError, HCHandshakeError:
                await self.appliance.close()
                msg = f"Can't connect to {self.config_entry.data[CONF_HOST]}, retrying"
                if first_failure:
                    self.logger.error(msg)  # noqa: TRY400
                    first_failure = False  # first_failure_fix
                else:
                    self.logger.debug(msg)
            except AllreadyConnectedError:
                await self.appliance.close()
                msg = f"Allready connected to {self.config_entry.data[CONF_HOST]}"
                self.logger.error(msg)  # noqa: TRY400
                return
            except Exception:
                await self.appliance.close()
                msg = f"Can't connect to {self.config_entry.data[CONF_HOST]}"
                self.logger.exception(msg)
            # Wait before the next attempt so an unreachable device does not cause a
            # tight connect/close loop. Skip the wait if close() ended the loop.
            if self._connecting:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_CONNECT_BACKOFF)

    async def _async_update_data(self) -> None:
        return None

    async def _connection_state_callback(self, event: ConnectionState) -> None:
        if event == ConnectionState.RECONNECTING:
            if not self._reconnecting:
                self._reconnecting = True
                reconnect_timeout = int(self.hass.loop.time()) + MAX_RECONECT_TIME
                self._reconnect_timer = self.hass.loop.call_at(
                    reconnect_timeout, self._connection_reconnect_callback
                )

        elif event == ConnectionState.CONNECTED:
            self.connected = True
            if self._reconnecting:
                self.logger.debug(
                    "Reconnected to %s",
                    self.config_entry.data[CONF_DESCRIPTION]["info"].get("vib"),
                )
                self._reconnecting = False
            self._cancel_reconnect_timer()

        elif event == ConnectionState.CLOSED:
            self.connected = False
            self._cancel_reconnect_timer()

        self.async_set_updated_data(None)

    def _cancel_reconnect_timer(self) -> None:
        # A stale timer from an earlier disconnect must not fire during a later
        # one and mark the coordinator disconnected before that cycle's own
        # grace period elapsed.
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()
            self._reconnect_timer = None

    def _connection_reconnect_callback(self) -> None:
        self._reconnect_timer = None
        if not self.appliance.session.connected:
            self.connected = False
            self.async_set_updated_data(None)
