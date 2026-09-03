"""Tests for entity descriptions."""

from __future__ import annotations

import json
from pathlib import Path
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
    generate_power_switch,
    generate_program,
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


def test_hob_energy_consumption_indication_switch_description() -> None:
    """Test the hob Energy Consumption Indication Setting is mapped as an enum switch."""
    description = next(
        item
        for item in COOKING_ENTITY_DESCRIPTIONS["switch"]
        if item.key == "switch_hob_energy_consumption_indication"
    )

    assert description.entity == "Cooking.Hob.Setting.EnergyConsumptionIndication"
    assert description.device_class is SwitchDeviceClass.SWITCH
    assert description.entity_category is EntityCategory.CONFIG
    # Enumeration Setting, so the on/off values have to be mapped explicitly
    assert description.value_mapping == ("IndicationOn", "IndicationOff")


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

    uid/access values are taken verbatim from the reporter profiles of upstream
    #351 and from the SX63HX52BE diagnostics.
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
    again on every state read. Upstream chris-mc1/homeconnect_local_hass hit the
    same class of bug (commit 3eaaac8). The fix here is architectural, not a
    None-guard: the description belongs under "event_sensor", like its grouped
    sibling generated in generate_hob_zones.
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

    Upstream issue #11: both static descriptions used the same key, so both
    switches collided on the same unique_id and Home Assistant silently
    dropped the second one.
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
