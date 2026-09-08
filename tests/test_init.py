"""Tests for integration init."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

import pytest
from custom_components.homeconnect_ws import (
    _set_finish_in_with_active_program,
    _wait_for_writable,
    coordinator,
)
from custom_components.homeconnect_ws.const import DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeconnect_websocket.entities import Access
from homeconnect_websocket.errors import CodeResponsError
from homeconnect_websocket.testutils import MockAppliance
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import DEVICE_DESCRIPTION, MOCK_CONFIG_DATA, MOCK_TLS_DEVICE_ID

if TYPE_CHECKING:
    from asyncio import Task
    from collections.abc import Coroutine

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


async def test_wait_for_writable_returns_immediately_when_already_writable() -> None:
    """No need to wait for a callback if the entity is already writable."""
    entity = MagicMock(access=Access.READ_WRITE)

    await _wait_for_writable(entity)

    entity.register_callback.assert_not_called()


async def test_wait_for_writable_waits_for_the_next_writable_update() -> None:
    """Waits for a descriptionChange NOTIFY flipping access, instead of firing blind."""
    entity = MagicMock(access=Access.READ)
    captured_callback = None

    def _capture(callback: object) -> None:
        nonlocal captured_callback
        captured_callback = callback

    entity.register_callback.side_effect = _capture

    async def _flip_access_soon() -> None:
        await asyncio.sleep(0)
        entity.access = Access.READ_WRITE
        assert captured_callback is not None
        await captured_callback(entity)

    flip_task = asyncio.ensure_future(_flip_access_soon())
    await _wait_for_writable(entity)
    await flip_task

    entity.unregister_callback.assert_called_once()


async def test_wait_for_writable_times_out_if_never_writable() -> None:
    """Fails clearly instead of hanging if the appliance never opens the window."""
    entity = MagicMock(access=Access.READ)

    with (
        patch("custom_components.homeconnect_ws._ACTIVE_PROGRAM_WRITABLE_TIMEOUT", 0.01),
        pytest.raises(ServiceValidationError),
    ):
        await _wait_for_writable(entity)

    entity.unregister_callback.assert_called_once()


async def test_set_finish_in_with_active_program_sends_combined_write() -> None:
    """The only format this class of appliance accepts: both uids in one /ro/values write."""
    appliance = MagicMock()
    active_program_entity = MagicMock(uid=256, access=Access.READ_WRITE)
    appliance.entities = {"BSH.Common.Root.ActiveProgram": active_program_entity}
    appliance.selected_program = MagicMock(uid=8213)
    appliance.session.send_sync = AsyncMock()
    finish_in_entity = MagicMock(uid=558)

    await _set_finish_in_with_active_program(appliance, finish_in_entity, 3600)

    appliance.session.send_sync.assert_called_once()
    message = appliance.session.send_sync.call_args[0][0]
    assert message.resource == "/ro/values"
    assert message.data == [
        {"uid": 558, "value": 3600},
        {"uid": 256, "value": 8213},
    ]


async def test_set_finish_in_with_active_program_raises_without_selected_program() -> None:
    """Nothing sensible to arm ActiveProgram to if no program is selected."""
    appliance = MagicMock()
    appliance.entities = {"BSH.Common.Root.ActiveProgram": MagicMock()}
    appliance.selected_program = None
    finish_in_entity = MagicMock(uid=558)

    with pytest.raises(ServiceValidationError):
        await _set_finish_in_with_active_program(appliance, finish_in_entity, 100)


async def test_set_finish_in_with_active_program_translates_code_response_error() -> None:
    """A rejected combined write still surfaces a clear, translated error."""
    appliance = MagicMock()
    active_program_entity = MagicMock(uid=256, access=Access.READ_WRITE)
    appliance.entities = {"BSH.Common.Root.ActiveProgram": active_program_entity}
    appliance.selected_program = MagicMock(uid=1)
    appliance.session.send_sync = AsyncMock(side_effect=CodeResponsError(541, "/ro/values"))
    finish_in_entity = MagicMock(uid=558)

    with pytest.raises(ServiceValidationError):
        await _set_finish_in_with_active_program(appliance, finish_in_entity, 100)


async def test_set_finish_in_falls_back_on_501_or_541(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected standalone write with code 501/541 triggers the combined-write fallback."""
    appliance, device_id = await _setup_entry_with_device(hass, monkeypatch)
    entity = Mock(uid=558, set_value=AsyncMock(side_effect=CodeResponsError(501, "/ro/values")))
    appliance.entities["BSH.Common.Option.FinishInRelative"] = entity

    with patch(
        "custom_components.homeconnect_ws._set_finish_in_with_active_program", AsyncMock()
    ) as fallback:
        await hass.services.async_call(
            DOMAIN,
            "set_finish_in",
            {"device_id": device_id, "finish_in": {"hours": 0, "minutes": 10, "seconds": 0}},
            blocking=True,
        )

    fallback.assert_awaited_once_with(appliance, entity, 600)


async def test_set_finish_in_does_not_fall_back_on_other_codes(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated rejection surfaces immediately instead of waiting up to 35s."""
    appliance, device_id = await _setup_entry_with_device(hass, monkeypatch)
    entity = Mock(uid=558, set_value=AsyncMock(side_effect=CodeResponsError(400, "/ro/values")))
    appliance.entities["BSH.Common.Option.FinishInRelative"] = entity

    with (
        patch(
            "custom_components.homeconnect_ws._set_finish_in_with_active_program", AsyncMock()
        ) as fallback,
        pytest.raises(ServiceValidationError),
    ):
        await hass.services.async_call(
            DOMAIN,
            "set_finish_in",
            {"device_id": device_id, "finish_in": {"hours": 0, "minutes": 10, "seconds": 0}},
            blocking=True,
        )

    fallback.assert_not_awaited()
