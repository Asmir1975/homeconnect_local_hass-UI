"""Tests for number entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_STEP,
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, ATTR_FRIENDLY_NAME, CONF_UNIT_OF_MEASUREMENT
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
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

    state = hass.states.get("number.fake_brand_homeappliance_number")
    assert state
    assert state.name == "Fake_brand HomeAppliance Number"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Number"
    assert state.attributes[ATTR_MIN] == 0
    assert state.attributes[ATTR_MAX] == 20
    assert state.attributes[ATTR_STEP] == 2


async def test_update(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating entity."""
    entity_id = "number.fake_brand_homeappliance_number"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Number"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state
    assert state.state == "0"

    await mock_appliance.entities["Test.Number"].update({"value": 10})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "10"

    await mock_appliance.entities["Test.Number"].update({"min": 10, "max": 50, "stepSize": 5})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_MIN] == 10
    assert state.attributes[ATTR_MAX] == 50
    assert state.attributes[ATTR_STEP] == 5


async def test_set_value(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test setting a value."""
    entity_id = "number.fake_brand_homeappliance_number"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: "2"},
        blocking=True,
    )
    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 204, "value": 2},
        )
    )


DURATION_ID = "number.fake_brand_homeappliance_duration"


def _duration_message(value: int) -> Message:
    return Message(
        resource="/ro/values",
        action=Action.POST,
        data={"uid": 205, "value": value},
    )


async def test_duration_accepts_multiple_of_step(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """A value on the step grid is sent to the appliance."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: DURATION_ID, ATTR_VALUE: 120},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(_duration_message(120))


async def test_duration_rejects_value_off_the_step_with_clear_message(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """A value the appliance would answer with 400 is rejected before sending."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: DURATION_ID, ATTR_VALUE: 121},
            blocking=True,
        )

    assert exc_info.value.translation_key == "invalid_step"
    assert exc_info.value.translation_placeholders == {
        "step": "60",
        "min": "60",
        "max": "1800",
        "unit": "s",
    }
    mock_appliance.session.send_sync.assert_not_awaited()


async def test_duration_in_minutes_has_a_usable_step(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Changing the unit to minutes keeps min, max and step consistent."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    state = hass.states.get(DURATION_ID)
    assert state.attributes[ATTR_STEP] == 60

    registry = er.async_get(hass)
    registry.async_update_entity_options(
        DURATION_ID, NUMBER_DOMAIN, {CONF_UNIT_OF_MEASUREMENT: "min"}
    )
    await hass.async_block_till_done()

    state = hass.states.get(DURATION_ID)
    assert state.attributes[ATTR_MIN] == 1
    assert state.attributes[ATTR_MAX] == 30
    assert state.attributes[ATTR_STEP] == 1

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: DURATION_ID, ATTR_VALUE: 2},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(_duration_message(120))


async def test_number_without_enforce_step_is_unchanged(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Other numbers keep sending whatever Home Assistant accepts."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.fake_brand_homeappliance_number", ATTR_VALUE: 3},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(resource="/ro/values", action=Action.POST, data={"uid": 204, "value": 3})
    )
