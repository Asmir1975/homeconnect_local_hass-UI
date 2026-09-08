"""The Home Connect Websocket integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Never

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DESCRIPTION, CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.util.hass_dict import HassKey
from homeconnect_websocket import CodeResponsError, Entity
from homeconnect_websocket.entities import Access
from homeconnect_websocket.message import Action
from homeconnect_websocket.message import Message as HC_Message

from .const import (
    CONF_DEV_OVERRIDE_HOST,
    CONF_DEV_OVERRIDE_PSK,
    CONF_DEV_SETUP_FROM_DUMP,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HomeConnectCoordinator
from .entity_descriptions import get_available_entities
from .helpers import error_decorator, get_config_entry_from_call

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant, ServiceCall, ServiceResponse
    from homeassistant.helpers.typing import ConfigType
    from homeconnect_websocket import HomeAppliance

    from .entity_descriptions import _EntityDescriptionsType

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: {
            vol.Optional(CONF_DEV_SETUP_FROM_DUMP, default=False): vol.Boolean(),
            vol.Optional(CONF_DEV_OVERRIDE_HOST): str,
            vol.Optional(CONF_DEV_OVERRIDE_PSK): str,
        }
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclass
class HCData:
    """Dataclass for runtime data."""

    appliance: HomeAppliance
    device_info: DeviceInfo
    available_entity_descriptions: _EntityDescriptionsType
    coordinator: HomeConnectCoordinator


@dataclass
class HCConfig:
    """Dataclass for hass.data."""

    setup_from_dump: bool = False
    override_host: str | None = None
    override_psk: str | None = None


type HCConfigEntry = ConfigEntry[HCData]

HC_KEY: HassKey[HCConfig] = HassKey(DOMAIN)

# Roughly one broadcast cycle - some appliances report ActiveProgram's access
# as READ_WRITE only for a narrow window on their own schedule. Long enough to
# catch the next window, short enough to fail fast if the appliance stops
# broadcasting it at all.
_ACTIVE_PROGRAM_WRITABLE_TIMEOUT = 35


def _raise_start_error(err: CodeResponsError) -> Never:
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="start_program_error",
        translation_placeholders={"code": err.code, "resource": err.resource},
    ) from None


async def _wait_for_writable(entity: Entity) -> None:
    """
    Wait for entity.access to allow a write, bounded to about one broadcast cycle.

    Some appliances broadcast a descriptionChange NOTIFY flipping an entity's
    access between READ and READ_WRITE on their own schedule rather than
    accepting a write at any time. AccessMixin already tracks the live access
    state, so wait for the next update that makes it writable instead of
    firing blind into a closed window.
    """
    if getattr(entity, "access", None) in (Access.READ_WRITE, Access.WRITE_ONLY):
        return
    became_writable = asyncio.Event()

    async def _on_update(_: Entity) -> None:
        if getattr(entity, "access", None) in (Access.READ_WRITE, Access.WRITE_ONLY):
            became_writable.set()

    entity.register_callback(_on_update)
    try:
        async with asyncio.timeout(_ACTIVE_PROGRAM_WRITABLE_TIMEOUT):
            await became_writable.wait()
    except TimeoutError:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="finish_in_not_writable",
        ) from None
    finally:
        entity.unregister_callback(_on_update)


async def _set_finish_in_with_active_program(
    appliance: HomeAppliance, finish_in_entity: Entity, seconds: int
) -> None:
    """
    Fall back for appliances where FinishInRelative can't be set on its own.

    Some appliances reject a standalone FinishInRelative write (CodeResponsError
    501 or 541) and only accept FinishInRelative and ActiveProgram written
    together in a single /ro/values message, sent while ActiveProgram's own
    access briefly reports READ_WRITE.
    """
    active_program_entity = appliance.entities.get("BSH.Common.Root.ActiveProgram")
    program = appliance.selected_program
    if active_program_entity is None or program is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_program_selected",
        )
    await _wait_for_writable(active_program_entity)
    message = HC_Message(
        resource="/ro/values",
        action=Action.POST,
        data=[
            {"uid": finish_in_entity.uid, "value": seconds},
            {"uid": active_program_entity.uid, "value": program.uid},
        ],
    )
    try:
        await appliance.session.send_sync(message)
    except CodeResponsError as exc:
        _raise_start_error(exc)


async def _set_finish_in_or_raise(
    appliance: HomeAppliance, finish_in_entity: Entity, seconds: int
) -> None:
    try:
        await finish_in_entity.set_value(seconds)
    except CodeResponsError as exc:
        # Only these two codes need the combined-write fallback; others are
        # real, unrelated rejections and should surface immediately.
        if exc.code not in (501, 541):
            _raise_start_error(exc)
        await _set_finish_in_with_active_program(appliance, finish_in_entity, seconds)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration global config."""
    hass.data.setdefault(DOMAIN, HCConfig())
    if DOMAIN in config:
        hass.data[HC_KEY].setup_from_dump = config[DOMAIN].get(CONF_DEV_SETUP_FROM_DUMP, False)
        hass.data[HC_KEY].override_host = config[DOMAIN].get(CONF_DEV_OVERRIDE_HOST)
        hass.data[HC_KEY].override_psk = config[DOMAIN].get(CONF_DEV_OVERRIDE_PSK)

    def _get_entity_or_raise(appliance: HomeAppliance, key: str, error_key: str) -> Entity:
        entity = appliance.entities.get(key)
        if not entity:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=error_key,
            )
        return entity

    def _duration_to_seconds(data: dict) -> int:
        return (
            int(data.get("hours", 0)) * 3600
            + int(data.get("minutes", 0)) * 60
            + int(data.get("seconds", 0))
        )

    async def _set_value_or_raise(entity: Entity, relative_time_in_seconds: int) -> None:
        try:
            await entity.set_value(relative_time_in_seconds)
        except CodeResponsError as exc:
            _raise_start_error(exc)

    @error_decorator
    async def handle_start_program(call: ServiceCall) -> ServiceResponse:
        config_entry = await get_config_entry_from_call(hass, call)

        options = {}
        appliance = config_entry.runtime_data.appliance
        if "start_in" in call.data:
            entity = _get_entity_or_raise(
                appliance, "BSH.Common.Option.StartInRelative", "start_in_not_available"
            )
            options[entity.uid] = _duration_to_seconds(call.data["start_in"])

        if "finish_in" in call.data:
            entity = _get_entity_or_raise(
                appliance, "BSH.Common.Option.FinishInRelative", "finish_in_not_available"
            )
            options[entity.uid] = _duration_to_seconds(call.data["finish_in"])

        if appliance.selected_program:
            try:
                await appliance.selected_program.start(options)
            except CodeResponsError as exc:
                _raise_start_error(exc)
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_program_selected",
            )

    @error_decorator
    async def handle_set_start_in(call: ServiceCall) -> ServiceResponse:
        config_entry = await get_config_entry_from_call(hass, call)
        appliance = config_entry.runtime_data.appliance
        await _set_value_or_raise(
            _get_entity_or_raise(
                appliance, "BSH.Common.Option.StartInRelative", "start_in_not_available"
            ),
            _duration_to_seconds(call.data["start_in"]),
        )

    @error_decorator
    async def handle_set_finish_in(call: ServiceCall) -> ServiceResponse:
        config_entry = await get_config_entry_from_call(hass, call)
        appliance = config_entry.runtime_data.appliance
        finish_in_entity = _get_entity_or_raise(
            appliance, "BSH.Common.Option.FinishInRelative", "finish_in_not_available"
        )
        await _set_finish_in_or_raise(
            appliance, finish_in_entity, _duration_to_seconds(call.data["finish_in"])
        )

    hass.services.async_register(DOMAIN, "start_program", handle_start_program)
    hass.services.async_register(DOMAIN, "set_start_in", handle_set_start_in)
    hass.services.async_register(DOMAIN, "set_finish_in", handle_set_finish_in)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HCConfigEntry,
) -> bool:
    """Set up this integration using config entry."""
    _LOGGER.debug("Setting up %s", config_entry.data[CONF_DESCRIPTION]["info"].get("model"))
    coordinator = HomeConnectCoordinator(hass, config_entry)
    appliance = coordinator.appliance
    device_info = DeviceInfo(
        hw_version=appliance.info.get("hwVersion"),
        identifiers={(DOMAIN, config_entry.unique_id)},
        model=f"{appliance.info.get('type')}",
        model_id=f"{appliance.info.get('vib')} / Host: {config_entry.data[CONF_HOST]}",
        sw_version=appliance.info.get("swVersion"),
    )

    if mac := appliance.info.get("mac"):
        device_info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(mac))}

    if brand := appliance.info.get("brand"):
        device_info["manufacturer"] = brand.capitalize()

    if (type_ := appliance.info.get("type")) and brand:
        device_info["name"] = f"{brand.capitalize()} {type_}"

    available_entities = get_available_entities(appliance)

    config_entry.runtime_data = HCData(
        appliance=appliance,
        device_info=device_info,
        available_entity_descriptions=available_entities,
        coordinator=coordinator,
    )

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    async def _async_stop_listener(_event: Event) -> None:
        """Close the connection on Home Assistant shutdown."""
        await coordinator.close()

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop_listener)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HCConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading %s", entry.data[CONF_DESCRIPTION]["info"].get("vib"))
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.close()
    return unload_ok
