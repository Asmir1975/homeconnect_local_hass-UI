"""Tests for integration init."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, Mock

from custom_components.homeconnect_ws import coordinator
from custom_components.homeconnect_ws.const import DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers import device_registry as dr
from homeconnect_websocket.testutils import MockAppliance
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import DEVICE_DESCRIPTION, MOCK_CONFIG_DATA, MOCK_TLS_DEVICE_ID

if TYPE_CHECKING:
    from asyncio import Task
    from collections.abc import Coroutine

    import pytest
    from homeassistant.core import HomeAssistant


async def test_load_unload_entry(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test setup and unload config entry."""
    appliance = MockAppliance(DEVICE_DESCRIPTION, "host", "mock_app", "mock_app_id", "PSK_KEY")
    appliance_mock = Mock(return_value=appliance)
    monkeypatch.setattr(coordinator, "HomeAppliance", appliance_mock)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    appliance_mock.assert_called_once_with(
        description=DEVICE_DESCRIPTION,
        host="1.2.3.4",
        app_name="Homeassistant",
        app_id="Test_Device_ID",
        psk64="PSK_KEY",
        iv64="AES_IV",
        connection_callback=ANY,
    )

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED

    appliance.session.close.assert_awaited_once()


async def test_stop_listener_closes_connection(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the appliance connection is closed when Home Assistant stops."""
    appliance = MockAppliance(DEVICE_DESCRIPTION, "host", "mock_app", "mock_app_id", "PSK_KEY")
    monkeypatch.setattr(coordinator, "HomeAppliance", Mock(return_value=appliance))

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    appliance.session.close.assert_awaited_once()


async def test_coordinator_connect_runs_as_background_task(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the initial connect is scheduled via async_create_background_task."""
    appliance = MockAppliance(DEVICE_DESCRIPTION, "host", "mock_app", "mock_app_id", "PSK_KEY")
    monkeypatch.setattr(coordinator, "HomeAppliance", Mock(return_value=appliance))

    calls = []
    original = ConfigEntry.async_create_background_task

    def spy(
        self: ConfigEntry,
        hass: HomeAssistant,
        target: Coroutine,
        name: str,
        *,
        eager_start: bool = True,
    ) -> Task:
        calls.append(name)
        return original(self, hass, target, name, eager_start=eager_start)

    monkeypatch.setattr(ConfigEntry, "async_create_background_task", spy)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert calls == ["homeconnect_ws_Fake_vib"]


async def _setup_entry_with_device(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> tuple[MockAppliance, str]:
    """Set up a config entry and return the appliance plus its device_id."""
    appliance = MockAppliance(DEVICE_DESCRIPTION, "host", "mock_app", "mock_app_id", "PSK_KEY")
    monkeypatch.setattr(coordinator, "HomeAppliance", Mock(return_value=appliance))

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    return appliance, devices[0].id


async def test_set_start_in_calls_set_value(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the set_start_in service actually awaits the entity write."""
    appliance, device_id = await _setup_entry_with_device(hass, monkeypatch)
    entity = Mock(uid=558, set_value=AsyncMock())
    appliance.entities["BSH.Common.Option.StartInRelative"] = entity

    await hass.services.async_call(
        DOMAIN,
        "set_start_in",
        {"device_id": device_id, "start_in": {"hours": 0, "minutes": 5, "seconds": 0}},
        blocking=True,
    )

    entity.set_value.assert_awaited_once_with(300)


async def test_set_finish_in_calls_set_value(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the set_finish_in service actually awaits the entity write."""
    appliance, device_id = await _setup_entry_with_device(hass, monkeypatch)
    entity = Mock(uid=559, set_value=AsyncMock())
    appliance.entities["BSH.Common.Option.FinishInRelative"] = entity

    await hass.services.async_call(
        DOMAIN,
        "set_finish_in",
        {"device_id": device_id, "finish_in": {"hours": 0, "minutes": 10, "seconds": 0}},
        blocking=True,
    )

    entity.set_value.assert_awaited_once_with(600)
