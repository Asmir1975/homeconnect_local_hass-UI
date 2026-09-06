"""Tests for sensor entity."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from custom_components.homeconnect_ws import HCData
from custom_components.homeconnect_ws.entity_descriptions.descriptions_definitions import (
    HCSensorEntityDescription,
)
from custom_components.homeconnect_ws.sensor import HCWiFI
from homeassistant.components.sensor import ATTR_OPTIONS
from homeassistant.const import ATTR_FRIENDLY_NAME

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

    state = hass.states.get("sensor.fake_brand_homeappliance_sensor")
    assert state
    assert state.name == "Fake_brand HomeAppliance Sensor"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Sensor"

    state = hass.states.get("sensor.fake_brand_homeappliance_sensor_enum")
    assert state
    assert state.name == "Fake_brand HomeAppliance Sensor.Enum"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Sensor.Enum"
    assert state.attributes[ATTR_OPTIONS] == ["Off", "On"]

    state = hass.states.get("sensor.fake_brand_homeappliance_sensor_event")
    assert state
    assert state.name == "Fake_brand HomeAppliance Sensor.Event"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Sensor.Event"
    assert state.attributes[ATTR_OPTIONS] == ["Event2", "Event1", "No Event"]

    state = hass.states.get("sensor.fake_brand_homeappliance_activeprogram")
    assert state
    assert state.name == "Fake_brand HomeAppliance ActiveProgram"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance ActiveProgram"
    assert state.attributes[ATTR_OPTIONS] == [
        "Named Favorite",
        "favorite_002",
        "test_program_program1",
        "test_program_program2",
    ]


async def test_update(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating entity."""
    entity_id = "sensor.fake_brand_homeappliance_sensor"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor"].update({"value": 5})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "5"


async def test_update_enum(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating entity with enum."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_enum"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.Enum"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Off"

    await mock_appliance.entities["Test.Sensor.Enum"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "On"


async def test_update_event(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating event sensor."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_event"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Event1"].update({"value": 0})
    await mock_appliance.entities["Test.Event2"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "No Event"

    await mock_appliance.entities["Test.Event1"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Event1"

    await mock_appliance.entities["Test.Event2"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Event2"

    await mock_appliance.entities["Test.Event2"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Event1"


async def test_update_active_program(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating active program entity."""
    entity_id = "sensor.fake_brand_homeappliance_activeprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.ActiveProgram"].update({"value": 500})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "test_program_program1"

    await mock_appliance.entities["Test.ActiveProgram"].update({"value": 502})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Named Favorite"


async def test_reset_when_operation_state_terminal(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Sensor must reset to 0 once OperationState is terminal, even with a stale value."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_resettable"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.Resettable"].update({"value": 42})
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 3})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "42"

    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "0"


async def test_reset_when_operation_state_finished(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Sensor must reset to 0 on Finished, matching the Gate-A oven repro."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_resettable"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.Resettable"].update({"value": 42})
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 6})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "0"


async def test_reset_when_operation_state_error_or_aborting(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Sensor must reset to 0 on Error and on Aborting."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_resettable"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.Resettable"].update({"value": 42})
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 7})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "0"

    await mock_appliance.entities["Test.Sensor.Resettable"].update({"value": 42})
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 8})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "0"


async def test_reset_when_operation_state_terminal_overrides_unavailable(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Sensor must show 0, not unavailable, when the device itself clears the entity."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_resettable"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.Resettable"].update(
        {"value": 42, "available": False}
    )
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "0"


async def test_reset_when_operation_state_terminal_not_reset_when_ready(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """A freshly selected program's estimated value must survive the Ready state."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_resettable"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.Resettable"].update({"value": 42})
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "42"


async def test_reset_when_operation_state_ready_if_also_reset_when_ready(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Progress/elapsed-style sensors must reset to 0 on Ready too, unlike a preview value."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_resettableonready"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.ResettableOnReady"].update(
        {"value": 42, "available": False}
    )
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "0"


async def test_reset_when_operation_state_run_if_also_reset_when_ready(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """A running program's own value must still survive, only Ready is added."""
    entity_id = "sensor.fake_brand_homeappliance_sensor_resettableonready"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor.ResettableOnReady"].update({"value": 42})
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 3})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "42"


async def test_unaffected_sensor_ignores_operation_state(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """A sensor without reset_when_operation_state_terminal must keep its stale value."""
    entity_id = "sensor.fake_brand_homeappliance_sensor"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Sensor"].update({"value": 5})
    await mock_appliance.entities["BSH.Common.Status.OperationState"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "5"


async def test_wifi_update() -> None:
    """Test the fallback WiFi sensor polling path."""
    appliance = MagicMock()
    appliance.info = {"deviceID": "test_device_id"}
    appliance.session.connected = True
    appliance.get_network_config = AsyncMock(return_value=[{"rssi": -62}])
    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=MagicMock(),
        coordinator=MagicMock(),
    )
    entity = HCWiFI(
        HCSensorEntityDescription(key="sensor_wifi_signal_strength"),
        runtime_data,
    )

    assert entity.should_poll
    await entity.async_update()

    assert entity.native_value == -62
    appliance.get_network_config.assert_awaited_once()


async def test_wifi_update_skips_when_not_connected() -> None:
    """Test that WiFi polling is skipped while disconnected."""
    appliance = MagicMock()
    appliance.info = {"deviceID": "test_device_id"}
    appliance.session.connected = False
    appliance.get_network_config = AsyncMock()
    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=MagicMock(),
        coordinator=MagicMock(),
    )
    entity = HCWiFI(
        HCSensorEntityDescription(key="sensor_wifi_signal_strength"),
        runtime_data,
    )

    await entity.async_update()

    assert entity.native_value is None
    appliance.get_network_config.assert_not_awaited()


async def test_wifi_updates_when_coordinator_connects(hass: HomeAssistant) -> None:
    """Test the first WiFi update after the appliance connects."""
    appliance = MagicMock()
    appliance.info = {"deviceID": "test_device_id"}
    appliance.session.connected = False
    appliance.get_network_config = AsyncMock(return_value=[{"rssi": -56}])
    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=MagicMock(),
        coordinator=MagicMock(),
    )
    entity = HCWiFI(
        HCSensorEntityDescription(key="sensor_wifi_signal_strength"),
        runtime_data,
    )
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()

    appliance.session.connected = True
    entity._handle_coordinator_update()
    await hass.async_block_till_done()

    assert entity.native_value == -56
    appliance.get_network_config.assert_awaited_once()
