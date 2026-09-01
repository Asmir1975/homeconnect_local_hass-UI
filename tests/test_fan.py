"""Tests for fan entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PERCENTAGE_STEP,
    SERVICE_SET_PERCENTAGE,
    SERVICE_TURN_OFF,
    FanEntityFeature,
)
from homeassistant.components.fan import DOMAIN as FAN_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    ATTR_SUPPORTED_FEATURES,
    STATE_OFF,
    STATE_ON,
)
from homeconnect_websocket.message import Action, Message

from . import setup_config_entry
from .const import MOCK_CONFIG_DATA

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeconnect_websocket.testutils import MockAppliance


async def test_setup(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,  # noqa: ARG001
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test setting up entity."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state
    assert state.name == "Fake_brand HomeAppliance Fan"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Fan"
    assert (
        state.attributes[ATTR_SUPPORTED_FEATURES]
        == FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_OFF
    )
    assert state.attributes[ATTR_PERCENTAGE_STEP] == 25


async def test_update(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating entity."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state.state == STATE_OFF

    await mock_appliance.entities["Test.FanSpeed1"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state.state == STATE_ON
    assert state.attributes[ATTR_PERCENTAGE] == 25

    await mock_appliance.entities["Test.FanSpeed1"].update({"value": 2})
    await hass.async_block_till_done()

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state.state == STATE_ON
    assert state.attributes[ATTR_PERCENTAGE] == 50

    await mock_appliance.entities["Test.FanSpeed1"].update({"value": 0})
    await mock_appliance.entities["Test.FanSpeed2"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state.state == STATE_ON
    assert state.attributes[ATTR_PERCENTAGE] == 75

    await mock_appliance.entities["Test.FanSpeed1"].update({"value": 0})
    await mock_appliance.entities["Test.FanSpeed2"].update({"value": 2})
    await hass.async_block_till_done()

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state.state == STATE_ON
    assert state.attributes[ATTR_PERCENTAGE] == 100


async def test_set_speed(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test setting a speed."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PERCENTAGE,
        {
            ATTR_ENTITY_ID: "fan.fake_brand_homeappliance_fan",
            ATTR_PERCENTAGE: 25,
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data=[{"uid": 403, "value": 1}, {"uid": 404, "value": 0}],
        )
    )
    mock_appliance.session.send_sync.reset_mock()

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PERCENTAGE,
        {
            ATTR_ENTITY_ID: "fan.fake_brand_homeappliance_fan",
            ATTR_PERCENTAGE: 75,
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data=[{"uid": 403, "value": 0}, {"uid": 404, "value": 1}],
        )
    )


async def test_is_on_false_when_operation_state_inactive(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Fan must report off once OperationState is inactive, even with a stale non-zero speed."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.FanSpeed1"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state.state == STATE_ON

    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get("fan.fake_brand_homeappliance_fan")
    assert state.state == STATE_OFF


async def test_turn_off_uses_power_state_when_settable(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Turning off must power the appliance down instead of zeroing the speed options."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "fan.fake_brand_homeappliance_fan"},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 205, "value": 1},
        )
    )


async def test_turn_off_ignores_power_state_value_outside_min_max(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """An enum value outside the declared min/max is not actually settable."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    # PowerState enum is {0: MainsOff, 1: Off, 2: On}; restrict the settable
    # range to On only, matching generate_power_switch's own range check.
    await mock_appliance.entities["BSH.Common.Setting.PowerState"].update({"min": 2, "max": 2})

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "fan.fake_brand_homeappliance_fan"},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data=[{"uid": 403, "value": 0}, {"uid": 404, "value": 0}],
        )
    )


async def test_turn_off_falls_back_to_zero_write_without_power_state(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Without a switchable PowerState, turn_off keeps the previous zero-write behavior."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    del mock_appliance.entities["BSH.Common.Setting.PowerState"]

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "fan.fake_brand_homeappliance_fan"},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data=[{"uid": 403, "value": 0}, {"uid": 404, "value": 0}],
        )
    )
