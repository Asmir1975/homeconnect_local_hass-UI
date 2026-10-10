"""Part B descriptors and translations; no live appliance connections."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from custom_components.homeconnect_ws import HCData
from custom_components.homeconnect_ws.entity import HCEntity
from custom_components.homeconnect_ws.entity_descriptions.cooking import (
    COOKING_ENTITY_DESCRIPTIONS,
)
from custom_components.homeconnect_ws.entity_descriptions.dishcare import (
    DISHCARE_ENTITY_DESCRIPTIONS,
)
from custom_components.homeconnect_ws.entity_descriptions.refrigeration import (
    REFRIGERATION_ENTITY_DESCRIPTIONS,
)
from custom_components.homeconnect_ws.sensor import HCSensor
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory

TRANSLATIONS = Path(__file__).parents[1] / "custom_components/homeconnect_ws/translations"
MAPPINGS = (
    (
        COOKING_ENTITY_DESCRIPTIONS,
        "sensor",
        "sensor_oven_steam_assist_level",
        "Cooking.Oven.Option.SteamAssistLevel",
        None,
    ),
    (
        COOKING_ENTITY_DESCRIPTIONS,
        "select",
        "select_oven_water_hardness",
        "Cooking.Oven.Setting.WaterHardness",
        EntityCategory.CONFIG,
    ),
    (
        REFRIGERATION_ENTITY_DESCRIPTIONS,
        "switch",
        "switch_freezer_auto_super",
        "Refrigeration.Common.Setting.Appliance.AutoSuper",
        EntityCategory.CONFIG,
    ),
    (
        DISHCARE_ENTITY_DESCRIPTIONS,
        "switch",
        "switch_dishwasher_gap_illumination",
        "Dishcare.Dishwasher.Setting.GapIllumination",
        EntityCategory.CONFIG,
    ),
    (
        DISHCARE_ENTITY_DESCRIPTIONS,
        "select",
        "select_dishwasher_interior_light_mode",
        "Dishcare.Dishwasher.Setting.InteriorLightMode",
        EntityCategory.CONFIG,
    ),
)


@pytest.mark.parametrize(("catalog", "platform", "key", "wire_name", "category"), MAPPINGS)
def test_part_b_mapping(
    catalog: dict, platform: str, key: str, wire_name: str, category: EntityCategory | None
) -> None:
    """Expose each new mapping once, using appliance enums for selects."""
    matching = [item for item in catalog[platform] if not callable(item) and item.key == key]
    assert len(matching) == 1
    description = matching[0]
    assert description.entity == wire_name
    assert description.entity_category == category
    if platform == "select":
        assert description.options is None
        assert description.has_state_translation
    elif platform == "sensor":
        assert description.device_class == SensorDeviceClass.ENUM
        assert description.has_state_translation


@pytest.mark.parametrize(
    ("platform", "key"),
    [
        ("switch", "switch_dishwasher_gap_illumination"),
        ("select", "select_dishwasher_interior_light_mode"),
    ],
)
def test_lights_force_disabled_despite_fork_default(platform: str, key: str) -> None:
    """Instantiate the entity to test the fork's enabled-default override."""
    description = next(item for item in DISHCARE_ENTITY_DESCRIPTIONS[platform] if item.key == key)
    assert not description.entity_registry_enabled_default
    assert description.force_disabled_default
    appliance = MagicMock()
    appliance.info = {"deviceID": "test_device"}
    runtime = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=MagicMock(),
        coordinator=MagicMock(),
    )
    assert not HCEntity(description, runtime).entity_registry_enabled_default


def test_steam_options_come_from_device_not_translation() -> None:
    """A generic medium translation cannot invent a NEFF steam level 2."""
    description = next(
        item
        for item in COOKING_ENTITY_DESCRIPTIONS["sensor"]
        if not callable(item) and item.key == "sensor_oven_steam_assist_level"
    )
    wire_entity = MagicMock()
    wire_entity.enum = {0: "Off", 1: "Low", 3: "High"}
    wire_entity.min = None
    wire_entity.max = None
    appliance = MagicMock()
    appliance.info = {"deviceID": "test_oven"}
    appliance.entities = {description.entity: wire_entity}
    runtime = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=MagicMock(),
        coordinator=MagicMock(),
    )
    entity = HCSensor(description, runtime)
    assert entity.options == ["off", "low", "high"]
    assert not any(
        not callable(item) and item.entity == description.entity
        for item in COOKING_ENTITY_DESCRIPTIONS["select"]
    )
    for value in ("Off", "Low", "High"):
        wire_entity.value = value
        assert entity.native_value == value.lower()
    wire_entity.value = None
    assert entity.native_value is None


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate JSON key: {key}"
        result[key] = value
    return result


@pytest.mark.parametrize("language", ["en", "de", "it"])
def test_part_b_translation_keys(language: str) -> None:
    """Check key coverage, not unverified app wording."""
    data = json.loads(
        (TRANSLATIONS / f"{language}.json").read_text(), object_pairs_hook=_unique_pairs
    )
    for _, platform, key, _, _ in MAPPINGS:
        assert data["entity"][platform][key]["name"]
    expected = {
        ("sensor", "sensor_oven_steam_assist_level"): {"off", "low", "medium", "high"},
        ("select", "select_oven_water_hardness"): {
            "softened",
            "soft",
            "medium",
            "hard",
            "veryhard",
        },
        ("select", "select_dishwasher_interior_light_mode"): {
            "applianceondooropen",
            "alwaysondooropen",
        },
    }
    for (platform, key), states in expected.items():
        assert set(data["entity"][platform][key]["state"]) == states
        assert all(data["entity"][platform][key]["state"].values())
    assert "select_oven_steam_assist_level" not in data["entity"]["select"]
