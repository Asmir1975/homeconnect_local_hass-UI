"""Tests for entity descriptions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

from custom_components.homeconnect_ws import HCData, entity_descriptions
from custom_components.homeconnect_ws.entity import HCEntity
from custom_components.homeconnect_ws.entity_descriptions import (
    HCBinarySensorEntityDescription,
    HCFanEntityDescription,
    HCLightEntityDescription,
    HCSelectEntityDescription,
    HCSensorEntityDescription,
    HCSwitchEntityDescription,
)
from custom_components.homeconnect_ws.entity_descriptions.common import (
    COMMON_ENTITY_DESCRIPTIONS,
    generate_elapsed_program_time,
    generate_power_switch,
    generate_program,
    generate_program_progress,
    generate_remaining_program_time,
    generate_start_button,
)
from custom_components.homeconnect_ws.entity_descriptions.cooking import (
    COOKING_ENTITY_DESCRIPTIONS,
    generate_hob_zones,
    generate_hood_fan,
)
from custom_components.homeconnect_ws.entity_descriptions.dishcare import (
    DISHCARE_ENTITY_DESCRIPTIONS,
)
from custom_components.homeconnect_ws.entity_descriptions.refrigeration import (
    generate_internal_light,
    generate_internal_light_brightness,
)
from custom_components.homeconnect_ws.helpers import entity_is_available, merge_dicts
from custom_components.homeconnect_ws.number import HCNumber
from custom_components.homeconnect_ws.sensor import HCEventSensor
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.number import NumberDeviceClass, NumberMode
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeconnect_websocket.entities import (
    Access,
    DeviceDescription,
    EntityDescription,
    Execution,
    OptionDescription,
)

if TYPE_CHECKING:
    import pytest
    from homeconnect_websocket.testutils import MockAppliance, MockApplianceType


def test_merge_dicts() -> None:
    """Test merge dicts."""
    dict1 = {"a": [1, 2], "b": [3, 4]}
    dict2 = {"b": [5, 6], "c": [7, 8]}
    out_dict = merge_dicts(dict1, dict2)
    assert out_dict == {"a": [1, 2], "b": [3, 4, 5, 6], "c": [7, 8]}


def test_machine_care_remaining_program_runs_description() -> None:
    """Test the Machine Care remaining-runs sensor metadata."""
    description = next(
        item
        for item in DISHCARE_ENTITY_DESCRIPTIONS["sensor"]
        if item.key == "sensor_machine_care_reminder"
    )

    assert (
        description.entity == "Dishcare.Dishwasher.Status.MachineCareReminder.RemainingProgramRuns"
    )
    assert description.native_unit_of_measurement is None
    assert description.state_class is SensorStateClass.MEASUREMENT


def test_dishwasher_active_option_descriptions() -> None:
    """Test the read-only mirrors for active dishwasher options."""
    descriptions = {item.key: item.entity for item in DISHCARE_ENTITY_DESCRIPTIONS["binary_sensor"]}

    assert descriptions["binary_sensor_intensiv_zone_active"] == (
        "Dishcare.Dishwasher.Option.IntensivZone"
    )
    assert descriptions["binary_sensor_half_load_active"] == ("Dishcare.Dishwasher.Option.HalfLoad")
    assert descriptions["binary_sensor_hygiene_plus_active"] == (
        "Dishcare.Dishwasher.Option.HygienePlus"
    )
    assert descriptions["binary_sensor_pretreatment_active"] == (
        "Dishcare.Dishwasher.Option.Pretreatment"
    )


def test_dishwasher_pretreatment_switch_description() -> None:
    """Test the writable dishwasher Pre-Treatment option."""
    description = next(
        item for item in DISHCARE_ENTITY_DESCRIPTIONS["switch"] if item.key == "switch_pretreatment"
    )

    assert description.entity == "Dishcare.Dishwasher.Option.Pretreatment"
    assert description.device_class is SwitchDeviceClass.SWITCH


def test_not_selectable_hob_zones_disabled_by_default() -> None:
    """Test that unavailable hob extension zones start disabled."""
    appliance = MagicMock()
    appliance.entities = {}
    zone_sensors = (
        "State",
        "OperationState",
        "PowerLevel",
        "FryingSensorLevel",
        "Duration",
        "ElapsedProgramTime",
        "RemainingProgramTime",
        "ProgramProgress",
    )
    extension_zones = {"120", "121", "201", "301", "340", "341"}
    for zone in {"100", *extension_zones}:
        for sensor in zone_sensors:
            entity = MagicMock()
            entity.value = (
                "NotSelectable" if zone in extension_zones and sensor == "State" else None
            )
            if zone == "100" and sensor == "State":
                entity.value = "Off"
            appliance.entities[f"Cooking.Hob.Status.Zone.{zone}.{sensor}"] = entity

    descriptions = generate_hob_zones(appliance)["sensor"]
    disabled = [item for item in descriptions if item.force_disabled_default]
    enabled = [item for item in descriptions if not item.force_disabled_default]

    assert len(disabled) == 48
    assert len(enabled) == 8
    assert all("_100_" in item.key for item in enabled)


def test_force_disabled_default_overrides_fork_default() -> None:
    """Test the narrow exception to the fork's enabled-by-default policy."""
    appliance = MagicMock()
    appliance.info = {"deviceID": "test_device_id"}
    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=MagicMock(),
        coordinator=MagicMock(),
    )

    entity = HCEntity(
        HCSensorEntityDescription(
            key="sensor_hob_zone_120_state",
            force_disabled_default=True,
        ),
        runtime_data,
    )

    assert not entity.entity_registry_enabled_default


MOCK_ENTITY_DESCRIPTIONS = {
    "binary_sensor": [
        HCBinarySensorEntityDescription(key="binary_sensor_available", entity="Test.BinarySensor"),
        HCBinarySensorEntityDescription(
            key="binary_sensor_not_available", entity="Test.BinarySensor2"
        ),
    ],
    "event_sensor": [
        HCSensorEntityDescription(
            key="sensor_event_available",
            entities=[
                "Test.Event1",
                "Test.Event2",
            ],
        ),
        HCSensorEntityDescription(
            key="sensor_event_not_available",
            entities=[
                "Test.Event1",
                "Test.Event3",
            ],
        ),
    ],
}


def test_get_available_entities(
    mock_appliance: MockAppliance, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test get_available_entities."""
    monkeypatch.setattr(
        entity_descriptions,
        "get_all_entity_description",
        Mock(return_value=MOCK_ENTITY_DESCRIPTIONS),
    )
    entities = entity_descriptions.get_available_entities(mock_appliance)
    assert entities["binary_sensor"] == [
        HCBinarySensorEntityDescription(key="binary_sensor_available", entity="Test.BinarySensor")
    ]
    assert entities["event_sensor"] == [
        HCSensorEntityDescription(
            key="sensor_event_available",
            entities=[
                "Test.Event1",
                "Test.Event2",
            ],
        )
    ]


POWER_SWITCH = {
    "setting": [
        {
            "access": "readwrite",
            "available": True,
            "enumeration": {"0": "MainsOff", "1": "Off", "2": "On", "3": "Standby"},
            "min": 0,
            "max": 2,
            "uid": 539,
            "name": "BSH.Common.Setting.PowerState",
        },
    ]
}


async def test_power_switch(mock_homeconnect_appliance: MockApplianceType) -> None:
    """Test dynamic Power switch."""
    device_description = POWER_SWITCH.copy()

    # On/Off Switch
    device_description["setting"][0]["min"] = 1
    device_description["setting"][0]["max"] = 2
    appliance = await mock_homeconnect_appliance(description=device_description)
    switch_description = generate_power_switch(appliance)

    assert switch_description["switch"][0] == HCSwitchEntityDescription(
        key="switch_power_state",
        entity="BSH.Common.Setting.PowerState",
        device_class=SwitchDeviceClass.SWITCH,
        value_mapping=("On", "Off"),
    )

    # No Switch
    device_description["setting"][0]["min"] = 0
    device_description["setting"][0]["max"] = 4
    appliance = await mock_homeconnect_appliance(description=device_description)
    switch_description = generate_power_switch(appliance)

    assert "switch" not in switch_description

    # On/MainsOff Switch
    device_description["setting"][0]["enumeration"] = {"0": "MainsOff", "2": "On"}
    appliance = await mock_homeconnect_appliance(description=device_description)
    switch_description = generate_power_switch(appliance)

    assert switch_description["switch"][0] == HCSwitchEntityDescription(
        key="switch_power_state",
        entity="BSH.Common.Setting.PowerState",
        device_class=SwitchDeviceClass.SWITCH,
        value_mapping=("On", "MainsOff"),
    )

    # Standby/Off Switch
    device_description["setting"][0]["enumeration"] = {"1": "Off", "3": "Standby"}
    appliance = await mock_homeconnect_appliance(description=device_description)
    switch_description = generate_power_switch(appliance)

    assert switch_description["switch"][0] == HCSwitchEntityDescription(
        key="switch_power_state",
        entity="BSH.Common.Setting.PowerState",
        device_class=SwitchDeviceClass.SWITCH,
        value_mapping=("Standby", "Off"),
    )


def test_read_only_hob_power_controls_disabled_by_default() -> None:
    """Test that read-only hob power controls start disabled."""
    appliance = MagicMock()
    appliance.info = {"type": "Hob"}
    power_state = MagicMock()
    power_state.access = Access.READ
    power_state.enum = {1: "Off", 2: "On"}
    power_state.min = 1
    power_state.max = 2
    appliance.entities = {"BSH.Common.Setting.PowerState": power_state}

    descriptions = generate_power_switch(appliance)

    assert descriptions["switch"][0].force_disabled_default
    assert descriptions["select"][0].force_disabled_default


def test_start_button_disabled_only_for_read_only_hob() -> None:
    """Test that only a read-only hob start button starts disabled."""
    appliance = MagicMock()
    appliance.programs = {
        "program": MagicMock(execution=Execution.SELECT_AND_START),
    }
    active_program = MagicMock()
    appliance.entities = {"BSH.Common.Root.ActiveProgram": active_program}

    appliance.info = {"type": "Hob"}
    active_program.access = Access.READ
    assert generate_start_button(appliance).force_disabled_default

    active_program.access = Access.READ_WRITE
    assert not generate_start_button(appliance).force_disabled_default

    appliance.info = {"type": "Dishwasher"}
    active_program.access = Access.READ
    assert not generate_start_button(appliance).force_disabled_default


PROGRAM = DeviceDescription(
    setting=[
        EntityDescription(
            uid=101,
            name="BSH.Common.Setting.Favorite.001.Name",
            access=Access.READ_WRITE,
            available=True,
            max=30,
            min=0,
            default="Named Favorite",
        ),
        EntityDescription(
            uid=102,
            name="BSH.Common.Setting.Favorite.002.Name",
            access=Access.READ_WRITE,
            available=True,
            max=30,
            min=0,
            default="",
        ),
    ],
    program=[
        EntityDescription(
            uid=201,
            name="BSH.Common.Program.Favorite.001",
            available=True,
        ),
        EntityDescription(
            uid=202,
            name="BSH.Common.Program.Favorite.002",
            available=True,
        ),
        EntityDescription(
            uid=500,
            name="BSH.Common.Program.Program1",
        ),
    ],
)


async def test_program(mock_homeconnect_appliance: MockApplianceType) -> None:
    """Test dynamic Program."""
    appliance = await mock_homeconnect_appliance(description=PROGRAM)
    program_description = generate_program(appliance)
    assert program_description["program"][0] == HCSelectEntityDescription(
        key="select_program",
        entity="BSH.Common.Root.SelectedProgram",
        has_state_translation=False,
        mapping={
            "BSH.Common.Program.Favorite.001": "Named Favorite",
            "BSH.Common.Program.Favorite.002": "favorite_002",
            "BSH.Common.Program.Program1": "bsh_common_program_program1",
        },
    )
    assert program_description["active_program"][0] == HCSensorEntityDescription(
        key="sensor_active_program",
        entity="BSH.Common.Root.ActiveProgram",
        has_state_translation=False,
        device_class=SensorDeviceClass.ENUM,
        mapping={
            "BSH.Common.Program.Favorite.001": "Named Favorite",
            "BSH.Common.Program.Favorite.002": "favorite_002",
            "BSH.Common.Program.Program1": "bsh_common_program_program1",
        },
    )

    appliance = await mock_homeconnect_appliance(description={})


async def test_hood_fan_requires_venting_program(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Fan speed options without the owning Program must not create a fan entity."""
    description = DeviceDescription(
        option=[
            EntityDescription(
                uid=401, name="Cooking.Common.Option.Hood.VentingLevel", access=Access.READ_WRITE
            ),
        ],
    )
    appliance = await mock_homeconnect_appliance(description=description)

    assert generate_hood_fan(appliance) is None


async def test_hood_fan_requires_options_owned_by_venting_program(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Speed entities not part of the Venting Program's options must not create a fan."""
    description = DeviceDescription(
        option=[
            EntityDescription(
                uid=401, name="Cooking.Common.Option.Hood.VentingLevel", access=Access.READ_WRITE
            ),
        ],
        program=[
            EntityDescription(
                uid=500,
                name="Cooking.Common.Program.Hood.Venting",
                options=[],
            ),
        ],
    )
    appliance = await mock_homeconnect_appliance(description=description)

    assert generate_hood_fan(appliance) is None


async def test_hood_fan_generated(mock_homeconnect_appliance: MockApplianceType) -> None:
    """Fan speed options owned by an existing Venting Program create the fan entity."""
    description = DeviceDescription(
        option=[
            EntityDescription(
                uid=401, name="Cooking.Common.Option.Hood.VentingLevel", access=Access.READ_WRITE
            ),
        ],
        program=[
            EntityDescription(
                uid=500,
                name="Cooking.Common.Program.Hood.Venting",
                options=[OptionDescription(refUID=401)],
            ),
        ],
    )
    appliance = await mock_homeconnect_appliance(description=description)

    assert generate_hood_fan(appliance) == HCFanEntityDescription(
        key="fan_hood",
        entities=["Cooking.Common.Option.Hood.VentingLevel"],
        default_program="Cooking.Common.Program.Hood.Venting",
    )


INTERNAL_LIGHT = DeviceDescription(
    setting=[
        EntityDescription(
            uid=501,
            name="Refrigeration.Common.Setting.Light.Internal.Power",
            access=Access.READ_WRITE,
            available=True,
        ),
        EntityDescription(
            uid=502,
            name="Refrigeration.Common.Setting.Light.Internal.Brightness",
            access=Access.READ_WRITE,
            available=True,
            min=0,
            max=100,
        ),
    ]
)


async def test_internal_light_with_brightness(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test power and brightness materialize as one dimmable light."""
    appliance = await mock_homeconnect_appliance(description=INTERNAL_LIGHT)
    appliance.info = {"deviceID": "test_device_id"}
    available = entity_descriptions.get_available_entities(appliance)

    lights = [item for item in available["light"] if item.key == "light_internal"]
    assert lights == [
        HCLightEntityDescription(
            key="light_internal",
            entity="Refrigeration.Common.Setting.Light.Internal.Power",
            brightness_entity="Refrigeration.Common.Setting.Light.Internal.Brightness",
        )
    ]

    brightness = next(
        item for item in available["number"] if item.key == "number_light_internal_brightness"
    )
    assert brightness.force_disabled_default

    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=available,
        coordinator=MagicMock(),
    )
    number = HCNumber(brightness, runtime_data)
    assert not number.entity_registry_enabled_default


async def test_internal_light_with_power_only(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test power without brightness remains an on-off light."""
    description = DeviceDescription(setting=[INTERNAL_LIGHT["setting"][0]])
    appliance = await mock_homeconnect_appliance(description=description)

    assert generate_internal_light(appliance) == HCLightEntityDescription(
        key="light_internal",
        entity="Refrigeration.Common.Setting.Light.Internal.Power",
    )
    assert generate_internal_light_brightness(appliance) is None


async def test_internal_light_with_brightness_only(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test brightness without power remains an enabled number."""
    description = DeviceDescription(setting=[INTERNAL_LIGHT["setting"][1]])
    appliance = await mock_homeconnect_appliance(description=description)
    appliance.info = {"deviceID": "test_device_id"}
    available = entity_descriptions.get_available_entities(appliance)

    assert generate_internal_light(appliance) is None
    brightness = next(
        item for item in available["number"] if item.key == "number_light_internal_brightness"
    )
    assert brightness == generate_internal_light_brightness(appliance)
    assert brightness.native_unit_of_measurement == PERCENTAGE
    assert brightness.mode is NumberMode.AUTO
    assert not brightness.force_disabled_default

    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=available,
        coordinator=MagicMock(),
    )
    number = HCNumber(brightness, runtime_data)
    assert number.entity_registry_enabled_default


def test_static_descriptions_have_english_name() -> None:
    """
    Test every static entity description resolves to a name in en.json.

    Entity names come from en.json keyed by translation_key, falling back to the
    description key. A description without a matching string silently produces an
    entity named after its object_id. Callable and dynamic descriptions are built
    at runtime and are not covered here.
    """
    en_path = Path(entity_descriptions.__file__).parents[1] / "translations" / "en.json"
    sections = json.loads(en_path.read_text(encoding="utf-8"))["entity"]

    missing = [
        (platform, key)
        for platform, items in entity_descriptions.get_all_entity_description().items()
        for item in items
        if not callable(item)
        and (key := item.translation_key or item.key)
        and not any(key in section for section in sections.values())
    ]

    assert missing == []


def test_delayed_shutoff_stage_translation_key_is_not_misspelled() -> None:
    """Test no translation file still uses the misspelled Delayed shut off stage key."""
    translations = Path(entity_descriptions.__file__).parents[1] / "translations"

    stale = [
        path.name
        for path in translations.glob("*.json")
        if "select_hob_delaye_shutoff_stage" in path.read_text(encoding="utf-8")
    ]

    assert stale == []


SILENCE_ON_DEMAND_PROFILE = {
    "setting": [
        {
            "access": "readwrite",
            "available": True,
            "min": 60,
            "max": 1800,
            "stepSize": 60,
            "uid": 4382,
            "name": "Dishcare.Dishwasher.Setting.SilenceOnDemandDefaultTime",
        },
    ],
    "status": [
        {
            "access": "read",
            "available": True,
            "uid": 4101,
            "name": "Dishcare.Dishwasher.Status.SilenceOnDemandRemainingTime",
        },
    ],
    "option": [
        {
            "access": "readwrite",
            "available": True,
            "uid": 5134,
            "name": "Dishcare.Dishwasher.Option.EcoDry",
        },
    ],
}


async def test_dishwasher_additions_materialize(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """
    Test the 1.10.5 dishwasher descriptions materialize on a real-profile shape.

    uid/access values are taken verbatim from reporter profiles and from the
    SX63HX52BE diagnostics.
    """
    appliance = await mock_homeconnect_appliance(description=SILENCE_ON_DEMAND_PROFILE)
    available = entity_descriptions.get_available_entities(appliance)

    number = next(
        item for item in available["number"] if item.key == "number_silence_on_demand_default_time"
    )
    assert number.entity == "Dishcare.Dishwasher.Setting.SilenceOnDemandDefaultTime"
    assert number.device_class is NumberDeviceClass.DURATION
    assert number.native_unit_of_measurement == UnitOfTime.SECONDS
    # min/max/step deliberately not hard coded: HCNumber reads them from the entity
    assert number.native_min_value is None
    assert number.native_max_value is None

    sensor = next(
        item
        for item in available["sensor"]
        if item.key == "sensor_silence_on_demand_remaining_time"
    )
    assert sensor.entity == "Dishcare.Dishwasher.Status.SilenceOnDemandRemainingTime"
    assert sensor.device_class is SensorDeviceClass.DURATION

    switch = next(item for item in available["switch"] if item.key == "switch_eco_dry")
    assert switch.entity == "Dishcare.Dishwasher.Option.EcoDry"
    assert switch.device_class is SwitchDeviceClass.SWITCH


async def test_silence_on_demand_default_time_follows_access(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test the duration Number tracks a read-write -> read -> read-write change."""
    appliance = await mock_homeconnect_appliance(description=SILENCE_ON_DEMAND_PROFILE)
    entity = appliance.entities["Dishcare.Dishwasher.Setting.SilenceOnDemandDefaultTime"]
    description = next(
        item
        for item in entity_descriptions.get_available_entities(appliance)["number"]
        if item.key == "number_silence_on_demand_default_time"
    )

    assert entity_is_available(entity, description.available_access)

    await entity.update({"access": Access.READ})
    assert not entity_is_available(entity, description.available_access)

    await entity.update({"access": Access.READ_WRITE})
    assert entity_is_available(entity, description.available_access)


OVEN_WATER_TANK_PROFILE = {
    "status": [
        {
            "access": "read",
            "available": True,
            "uid": 8001,
            "name": "Cooking.Oven.Status.WaterTankUnplugged",
        },
        {
            "access": "read",
            "available": True,
            "uid": 8002,
            "name": "Cooking.Oven.Status.WaterTankEmpty",
        },
    ],
}


async def test_oven_water_tank_is_an_event_sensor(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """
    Test the oven water tank description does not crash as a plain sensor.

    A static HCSensorEntityDescription with entities= instead of entity= leaves
    HCEntity._entity as None. HCSensor.__init__ and HCSensor.native_value both
    read self._entity directly, so the "sensor" platform crashes on setup and
    again on every state read. The fix is architectural, not a None-guard: the
    description belongs under "event_sensor", like its grouped sibling generated
    in generate_hob_zones.
    """
    appliance = await mock_homeconnect_appliance(description=OVEN_WATER_TANK_PROFILE)
    appliance.info = {"deviceID": "test_device_id"}
    available = entity_descriptions.get_available_entities(appliance)

    description = next(
        item for item in available["event_sensor"] if item.key == "sensor_oven_water_tank"
    )
    assert not any(item.key == "sensor_oven_water_tank" for item in available["sensor"])

    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=available,
        coordinator=MagicMock(),
    )
    sensor = HCEventSensor(description, runtime_data)

    unplugged = appliance.entities["Cooking.Oven.Status.WaterTankUnplugged"]
    empty = appliance.entities["Cooking.Oven.Status.WaterTankEmpty"]

    await unplugged.update({"value": True})
    await empty.update({"value": False})
    assert sensor.native_value == "unplugged"

    await unplugged.update({"value": False})
    await empty.update({"value": True})
    assert sensor.native_value == "empty"

    await empty.update({"value": False})
    assert sensor.native_value == "ok"


OVEN_PROGRAM_TIME_PROFILE = DeviceDescription(
    status=[
        EntityDescription(
            uid=9001,
            name="Cooking.Oven.Status.Cavity.001.ProgramProgress",
            available=True,
            access=Access.READ,
        ),
    ],
    option=[
        EntityDescription(
            uid=9002, name="BSH.Common.Option.ProgramProgress", available=True, access=Access.READ
        ),
        EntityDescription(
            uid=9003,
            name="BSH.Common.Option.RemainingProgramTime",
            available=True,
            access=Access.READ,
        ),
        EntityDescription(
            uid=9004,
            name="BSH.Common.Option.ElapsedProgramTime",
            available=True,
            access=Access.READ,
        ),
    ],
)


async def test_oven_program_time_sensors_reset_on_terminal_state(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test the reset flag turns on when an oven cavity status entity is present."""
    appliance = await mock_homeconnect_appliance(description=OVEN_PROGRAM_TIME_PROFILE)

    assert generate_program_progress(appliance).reset_when_operation_state_terminal
    assert generate_remaining_program_time(appliance).reset_when_operation_state_terminal
    assert generate_elapsed_program_time(appliance).reset_when_operation_state_terminal
    # Progress/elapsed have no legitimate non-zero preview value in Ready,
    # unlike remaining time (a preview of the selected program's duration).
    assert generate_program_progress(appliance).also_reset_when_ready
    assert generate_elapsed_program_time(appliance).also_reset_when_ready
    assert not generate_remaining_program_time(appliance).also_reset_when_ready


async def test_non_oven_program_time_sensors_keep_default_behavior(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test the reset flag stays off for a device without an oven cavity, e.g. a dishwasher."""
    description = DeviceDescription(option=OVEN_PROGRAM_TIME_PROFILE["option"])
    appliance = await mock_homeconnect_appliance(description=description)

    assert not generate_program_progress(appliance).reset_when_operation_state_terminal
    assert not generate_remaining_program_time(appliance).reset_when_operation_state_terminal
    assert not generate_elapsed_program_time(appliance).reset_when_operation_state_terminal
    assert not generate_program_progress(appliance).also_reset_when_ready
    assert not generate_elapsed_program_time(appliance).also_reset_when_ready


# UIDs and names from the EX851LYV5E profile.
HOB_ELAPSED_TIME_PROFILE = DeviceDescription(
    status=[
        EntityDescription(
            uid=8203,
            name="Cooking.Hob.Status.Zone.100.OperationState",
            available=True,
            access=Access.READ,
        ),
        EntityDescription(
            uid=8209,
            name="Cooking.Hob.Status.Zone.100.ElapsedProgramTime",
            available=True,
            access=Access.READ,
        ),
    ],
    option=[
        EntityDescription(
            uid=528, name="BSH.Common.Option.ElapsedProgramTime", available=True, access=Access.READ
        ),
    ],
)


async def test_hob_elapsed_time_resets_on_terminal_state(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """
    Test the hob elapsed time sensors reset on a terminal state, not on Ready.

    Device log 2026-10-04 10:27:31: the hob went from Run to Inactive and kept
    sending 1770 s for the zone and the appliance. Via Ready (09:26:23) it sent 0
    itself, so Ready needs no overlay.
    """
    appliance = await mock_homeconnect_appliance(description=HOB_ELAPSED_TIME_PROFILE)

    elapsed = generate_elapsed_program_time(appliance)
    assert elapsed.reset_when_operation_state_terminal
    assert not elapsed.also_reset_when_ready

    zone_descriptions = {item.key: item for item in generate_hob_zones(appliance)["sensor"]}
    zone_elapsed = zone_descriptions["sensor_hob_zone_100_elapsed_program_time"]
    assert zone_elapsed.reset_when_operation_state_terminal
    assert not zone_elapsed.also_reset_when_ready
    assert not zone_descriptions[
        "sensor_hob_zone_100_operationstate"
    ].reset_when_operation_state_terminal


def _speed_perfect_option(name: str, uid: int) -> dict:
    return {
        "access": "readwrite",
        "available": True,
        "uid": uid,
        "name": name,
    }


COMMON_SPEED_PERFECT = "LaundryCare.Common.Option.SpeedPerfect"
WASHER_SPEED_PERFECT = "LaundryCare.Washer.Option.SpeedPerfect"


async def test_washer_only_speed_perfect_keeps_existing_key(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test a washer without the Common option keeps its established key."""
    appliance = await mock_homeconnect_appliance(
        description={"option": [_speed_perfect_option(WASHER_SPEED_PERFECT, 7001)]}
    )
    available = entity_descriptions.get_available_entities(appliance)

    switch = next(item for item in available["switch"] if item.entity == WASHER_SPEED_PERFECT)
    assert switch.key == "switch_laundry_speed_perfect"


async def test_speed_perfect_descriptions_have_unique_keys(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """
    Test a washer reporting both SpeedPerfect options gets two distinct switches.

    Both static descriptions used the same key, so both switches collided on the
    same unique_id and Home Assistant silently dropped the second one.
    """
    appliance = await mock_homeconnect_appliance(
        description={
            "option": [
                _speed_perfect_option(COMMON_SPEED_PERFECT, 7002),
                _speed_perfect_option(WASHER_SPEED_PERFECT, 7003),
            ]
        }
    )
    available = entity_descriptions.get_available_entities(appliance)

    speed_perfect = [
        item
        for item in available["switch"]
        if item.entity in (COMMON_SPEED_PERFECT, WASHER_SPEED_PERFECT)
    ]
    assert len(speed_perfect) == 2
    assert len({item.key for item in speed_perfect}) == 2


def test_hood_ambient_light_color_select_description() -> None:
    """Test the ambient light color preset Select uses the raw device enum."""
    description = next(
        item
        for item in COOKING_ENTITY_DESCRIPTIONS["select"]
        if item.key == "select_hood_ambient_light_color"
    )

    assert description.entity == "BSH.Common.Setting.AmbientLightColor"
    assert description.has_state_translation is True


def test_hood_color_temperature_select_description() -> None:
    """Test the light color temperature preset Select uses the raw device enum."""
    description = next(
        item
        for item in COOKING_ENTITY_DESCRIPTIONS["select"]
        if item.key == "select_hood_color_temperature"
    )

    assert description.entity == "Cooking.Hood.Setting.ColorTemperature"
    assert description.has_state_translation is True
    assert description.entity_category == EntityCategory.CONFIG


def test_hood_setting_selects_use_raw_device_enum() -> None:
    """Test the hood setting Selects map to their Setting with translated states."""
    selects = {
        item.key: item for item in COOKING_ENTITY_DESCRIPTIONS["select"] if not callable(item)
    }
    expected = {
        "select_hood_ventilation_startup": "Cooking.Hood.Setting.VentilationStartupSetting",
        "select_hood_ventilation_shutdown": "Cooking.Hood.Setting.VentilationShutdownSetting",
        "select_hood_ventilation_profile": "Cooking.Hood.Setting.VentilationProfileOperating",
        "select_hood_filter_notification": (
            "Cooking.Hood.Setting.FilterSaturationNotificationInterval"
        ),
    }
    for key, entity in expected.items():
        assert selects[key].entity == entity
        assert selects[key].has_state_translation is True
        assert selects[key].entity_category == EntityCategory.CONFIG


def test_hood_interval_numbers_match_their_setting() -> None:
    """Test the interval on/off Numbers read the Setting their name says."""
    numbers = {item.key: item.entity for item in COOKING_ENTITY_DESCRIPTIONS["number"]}

    assert numbers["number_hood_interval_on"] == "Cooking.Hood.Setting.IntervalTimeOn"
    assert numbers["number_hood_interval_off"] == "Cooking.Hood.Setting.IntervalTimeOff"


def test_hood_favorite_functionality_select_only_for_hoods() -> None:
    """Test the favorite button Select is offered for hoods only."""
    generators = [
        item
        for item in COOKING_ENTITY_DESCRIPTIONS["select"]
        if callable(item) and "favorite" in item.__qualname__
    ]
    assert len(generators) == 2
    entities = {
        "BSH.Common.Setting.Favorite.001.Functionality": None,
        "BSH.Common.Setting.Favorite.002.Functionality": None,
    }

    hood = SimpleNamespace(info={"type": "Hood"}, entities=entities)
    keys = [generate(hood).key for generate in generators]
    assert keys == [
        "select_hood_favorite_001_functionality",
        "select_hood_favorite_002_functionality",
    ]
    assert all(generate(hood).entity_category == EntityCategory.CONFIG for generate in generators)

    for appliance_type in ("Oven", "Dishwasher"):
        other = SimpleNamespace(info={"type": appliance_type}, entities=entities)
        assert all(generate(other) is None for generate in generators)

    empty_hood = SimpleNamespace(info={"type": "Hood"}, entities={})
    assert all(generate(empty_hood) is None for generate in generators)


def test_favorite_trigger_sensors_disabled_by_default_for_hoods() -> None:
    """Test the favorite button Binary Sensors start disabled on hoods only."""
    generators = [
        item
        for item in COMMON_ENTITY_DESCRIPTIONS["binary_sensor"]
        if callable(item) and "favorite" in item.__qualname__
    ]
    assert len(generators) == 2
    entities = {
        "BSH.Common.Event.Favorite.001.ExternalTrigger": None,
        "BSH.Common.Event.Favorite.002.ExternalTrigger": None,
    }

    hood = SimpleNamespace(info={"type": "Hood"}, entities=entities)
    hood_descriptions = [generate(hood) for generate in generators]
    assert [item.key for item in hood_descriptions] == [
        "binary_sensor_favorite_001",
        "binary_sensor_favorite_002",
    ]
    assert all(item.force_disabled_default for item in hood_descriptions)

    hob = SimpleNamespace(info={"type": "Hob"}, entities=entities)
    assert not any(generate(hob).force_disabled_default for generate in generators)

    empty = SimpleNamespace(info={"type": "Hood"}, entities={})
    assert all(generate(empty) is None for generate in generators)


def test_hood_regenerative_carbon_filter_sensors() -> None:
    """Test the two new regenerative carbon filter percentage sensors."""
    keys = {
        "sensor_regenerative_carbon_filter_life_cycle": (
            "Cooking.Hood.Status.RegenerativeCarbonFilterLifeCycle"
        ),
        "sensor_regenerative_carbon_filter_saturation": (
            "Cooking.Hood.Status.RegenerativeCarbonFilterSaturation"
        ),
    }
    for key, entity in keys.items():
        description = next(
            item for item in COOKING_ENTITY_DESCRIPTIONS["sensor"] if item.key == key
        )
        assert description.entity == entity
        assert description.native_unit_of_measurement == PERCENTAGE


def test_hood_filter_event_binary_sensors_disabled_by_default() -> None:
    """Test the seven filter event Binary Sensors: entity, on/off values, disabled default."""
    keys_to_entities = {
        "binary_sensor_hood_carbon_filter_max_saturation_reached": (
            "Cooking.Common.Event.Hood.CarbonFilterMaxSaturationReached"
        ),
        "binary_sensor_hood_carbon_filter_max_saturation_nearly_reached": (
            "Cooking.Common.Event.Hood.CarbonFilterMaxSaturationNearlyReached"
        ),
        "binary_sensor_hood_grease_filter_max_saturation_reached": (
            "Cooking.Common.Event.Hood.GreaseFilterMaxSaturationReached"
        ),
        "binary_sensor_hood_grease_filter_max_saturation_nearly_reached": (
            "Cooking.Common.Event.Hood.GreaseFilterMaxSaturationNearlyReached"
        ),
        "binary_sensor_hood_regenerative_carbon_filter_max_saturation_reached": (
            "Cooking.Common.Event.Hood.RegenerativeCarbonFilterMaxSaturationReached"
        ),
        "binary_sensor_hood_regenerative_carbon_filter_lifetime_exceeded": (
            "Cooking.Common.Event.Hood.RegenerativeCarbonFilterLifeTimeExceeded"
        ),
        "binary_sensor_hood_regenerative_carbon_filter_lifetime_nearly_exceeded": (
            "Cooking.Common.Event.Hood.RegenerativeCarbonFilterLifeTimeNearlyExceeded"
        ),
    }
    by_key = {item.key: item for item in COOKING_ENTITY_DESCRIPTIONS["binary_sensor"]}
    assert set(by_key) == set(keys_to_entities)
    for key, entity in keys_to_entities.items():
        description = by_key[key]
        assert description.entity == entity
        assert description.device_class is BinarySensorDeviceClass.PROBLEM
        assert description.value_on == {"Present", "Confirmed"}
        assert description.value_off == {"Off"}
        assert description.force_disabled_default is True
        assert description.entity_category is EntityCategory.DIAGNOSTIC


def _settings(*entries: tuple) -> DeviceDescription:
    return DeviceDescription(
        setting=[
            EntityDescription(
                uid=uid,
                name=name,
                available=True,
                access=Access.READ_WRITE,
                **({"enumeration": enumeration} if enumeration else {}),
            )
            for uid, name, enumeration in entries
        ]
    )


# UIDs, names and enumerations from the EX851LYV5E profile.
HOB_SETTINGS_PROFILE = _settings(
    (524, "BSH.Common.Setting.ChildLock", None),
    (
        4352,
        "Cooking.Hob.Setting.AutomaticKeyLock",
        {"0": "Deactivated", "1": "Activated", "2": "KeyLockFunctionDeactivated"},
    ),
    (
        4353,
        "Cooking.Hob.Setting.BuzzerBeepLevel",
        {"0": "AllOff", "1": "AcknowledgeOff", "2": "WarningMalOff", "3": "AllActive"},
    ),
    (
        4354,
        "Cooking.Hob.Setting.EnergyConsumptionIndication",
        {"0": "IndicationOff", "1": "IndicationOn"},
    ),
    (4356, "Cooking.Hob.Setting.AutomaticTimer", None),
    (
        4358,
        "Cooking.Hob.Setting.EndTimerSignalduration",
        {"1": "10seconds", "2": "30seconds", "3": "60seconds"},
    ),
    (4369, "Cooking.Hob.Setting.BridgeZoneMode", {"0": "SplitMode", "1": "JoinMode"}),
    (4360, "Cooking.Hob.Setting.PowerManagement", {"0": "Off", "10": "1000W", "90": "9000W"}),
    (
        4375,
        "Cooking.Hob.Setting.HoodAutomaticStart",
        {"0": "Off", "1": "AutomaticMode", "2": "ManualMode"},
    ),
    (
        4377,
        "Cooking.Hob.Setting.HoodAfterRun",
        {"0": "Off", "1": "AutomaticMode", "2": "ManualMode", "3": "DoNothing"},
    ),
    (4378, "Cooking.Hob.Setting.HoodAutomaticLightOn", {"0": "Off", "1": "On"}),
    (4379, "Cooking.Hob.Setting.HoodAutomaticLightOff", {"0": "Off", "1": "On"}),
    (
        4380,
        "Cooking.Hob.Setting.PowerMoveModeDefaultValueFrontLeft",
        {"0": "Off", "1": "KeepWarm", "2": "10", "10": "50", "18": "90", "20": "Boost1"},
    ),
    (
        4381,
        "Cooking.Hob.Setting.PowerMoveModeDefaultValueMiddleLeft",
        {"0": "Off", "1": "KeepWarm", "2": "10", "10": "50", "18": "90", "20": "Boost1"},
    ),
    (
        4382,
        "Cooking.Hob.Setting.PowerMoveModeDefaultValueRearLeft",
        {"0": "Off", "1": "KeepWarm", "2": "10", "10": "50", "18": "90", "20": "Boost1"},
    ),
    (
        4383,
        "Cooking.Hob.Setting.PowerMoveModeDefaultValueFrontRight",
        {"0": "Off", "1": "KeepWarm", "2": "10", "10": "50", "18": "90", "20": "Boost1"},
    ),
    (
        4384,
        "Cooking.Hob.Setting.PowerMoveModeDefaultValueMiddleRight",
        {"0": "Off", "1": "KeepWarm", "2": "10", "10": "50", "18": "90", "20": "Boost1"},
    ),
    (
        4385,
        "Cooking.Hob.Setting.PowerMoveModeDefaultValueRearRight",
        {"0": "Off", "1": "KeepWarm", "2": "10", "10": "50", "18": "90", "20": "Boost1"},
    ),
)

# UIDs, names and enumerations from the HB774G1B1 profile.
OVEN_SETTINGS_PROFILE = _settings(
    (524, "BSH.Common.Setting.ChildLock", None),
    (
        4354,
        "Cooking.Oven.Setting.ClockDisplay",
        {"3": "AnalogClock", "5": "DigitalClock", "6": "DigitalClockAndDate"},
    ),
    (4357, "Cooking.Oven.Setting.DisplayBrandLogo", None),
    (4366, "Cooking.Oven.Setting.TeloscopicSlideOutRefited", None),
    (4425, "Cooking.Oven.Setting.ClockPrompt", {"0": "Off", "1": "On", "2": "OnEnergySaving"}),
    (4392, "Cooking.Oven.Setting.CountUpTimer", {"0": "NotShown", "1": "FromStart"}),
    (4394, "Cooking.Oven.Setting.Dishes", {"0": "All", "1": "NoPork", "2": "KosherOnly"}),
    (
        4398,
        "Cooking.Oven.Setting.ConfigureChildLock",
        {"0": "Deactivated", "1": "Activated", "2": "ActivatedWithDoorlock"},
    ),
    (4411, "Cooking.Oven.Setting.FastPreHeat", None),
    (4427, "Cooking.Oven.Setting.RegionalDishes", {"0": "All", "1": "European", "2": "British"}),
    (
        4428,
        "Cooking.Oven.Setting.StartupMenu",
        {"0": "MainMenue", "1": "HeatingModes", "5": "Dishes", "10": "Favorites"},
    ),
    (4432, "Cooking.Oven.Setting.CavityIllumination", {"0": "On", "1": "RestrictedOn", "2": "Off"}),
)


async def test_hob_settings_follow_the_app(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test the hob settings become config entities, the child lock as a select only."""
    appliance = await mock_homeconnect_appliance(description=HOB_SETTINGS_PROFILE)
    entities = entity_descriptions.get_available_entities(appliance)

    assert {item.key for item in entities["select"]} == {
        "select_hob_automatic_key_lock",
        "select_hob_bridge_zone_mode",
        "select_hob_buzzer_beep_level",
        "select_hob_energy_consumption_indication",
        "select_hob_end_timer_signal_duration",
        "select_hob_power_management",
        "select_hob_hood_automatic_start",
        "select_hob_hood_after_run",
        "select_hob_hood_automatic_light_on",
        "select_hob_hood_automatic_light_off",
        "select_hob_power_move_front_left",
        "select_hob_power_move_middle_left",
        "select_hob_power_move_rear_left",
        "select_hob_power_move_front_right",
        "select_hob_power_move_middle_right",
        "select_hob_power_move_rear_right",
    }
    assert not entities.get("switch")
    timer = next(item for item in entities["number"] if item.key == "number_hob_automatic_timer")
    assert timer.mode is NumberMode.SLIDER


async def test_oven_settings_follow_the_app(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test the oven settings become config entities, the child lock as a select only."""
    appliance = await mock_homeconnect_appliance(description=OVEN_SETTINGS_PROFILE)
    entities = entity_descriptions.get_available_entities(appliance)

    assert {item.key for item in entities["select"]} == {
        "select_oven_child_lock_setting",
        "select_oven_clock_display",
        "select_oven_clock_prompt",
        "select_oven_count_up_timer",
        "select_oven_dishes",
        "select_oven_regional_dishes",
        "select_oven_startup_menu",
        "select_oven_cavity_illumination",
    }
    assert {item.key for item in entities["switch"]} == {
        "switch_oven_display_brand_logo",
        "switch_oven_fast_pre_heat_setting",
        "switch_oven_telescopic_slide_out",
    }


async def test_child_lock_switch_without_child_lock_select(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test appliances without a child lock select keep the ChildLock switch."""
    appliance = await mock_homeconnect_appliance(
        description=_settings((524, "BSH.Common.Setting.ChildLock", None))
    )
    entities = entity_descriptions.get_available_entities(appliance)

    assert [item.key for item in entities["switch"]] == ["switch_child_lock"]


async def test_allow_backend_connection_switch(
    mock_homeconnect_appliance: MockApplianceType,
) -> None:
    """Test AllowBackendConnection becomes a config switch."""
    # UID and name from the SX63HX52BE profile.
    appliance = await mock_homeconnect_appliance(
        description=_settings((3, "BSH.Common.Setting.AllowBackendConnection", None))
    )
    entities = entity_descriptions.get_available_entities(appliance)

    switch = next(
        item for item in entities["switch"] if item.key == "switch_allow_backend_connection"
    )
    assert switch.entity == "BSH.Common.Setting.AllowBackendConnection"
    assert switch.entity_category is EntityCategory.CONFIG
    assert switch.force_disabled_default
