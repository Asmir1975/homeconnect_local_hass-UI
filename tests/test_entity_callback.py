"""Tests for HCEntity.callback recovery after a failing state write."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.homeconnect_ws.entity import HCEntity

from . import setup_config_entry
from .const import MOCK_CONFIG_DATA

if TYPE_CHECKING:
    import pytest
    from homeassistant.core import HomeAssistant
    from homeconnect_websocket.testutils import MockAppliance

ENTITY_ID = "sensor.fake_brand_homeappliance_sensor"


async def test_callback_recovers_after_failing_state_write(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising async_write_ha_state() must not permanently stop later updates."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    original_write = HCEntity.async_write_ha_state
    should_raise = {"value": True}

    def _write(self: HCEntity) -> None:
        if self.entity_id == ENTITY_ID and should_raise["value"]:
            should_raise["value"] = False
            msg = "boom"
            raise ValueError(msg)
        original_write(self)

    monkeypatch.setattr(HCEntity, "async_write_ha_state", _write)

    # First update: the state write raises. The library's callback wrapper
    # logs and swallows it, so this must not propagate here.
    await mock_appliance.entities["Test.Sensor"].update({"value": "41"})
    await hass.async_block_till_done()

    # Second update: without the try/finally guard, _has_callback stays True
    # forever and this write is silently skipped.
    await mock_appliance.entities["Test.Sensor"].update({"value": "42"})
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.state == "42"
