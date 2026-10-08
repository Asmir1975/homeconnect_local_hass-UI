"""Additional appliance mappings and translation coverage; no live connections."""

import json
from pathlib import Path

from custom_components.homeconnect_ws.entity_descriptions.dishcare import (
    DISHCARE_ENTITY_DESCRIPTIONS,
)
from homeassistant.const import EntityCategory

TRANSLATIONS = Path(__file__).parents[1] / "custom_components/homeconnect_ws/translations"


def test_dishwasher_light_configuration_descriptions() -> None:
    """Keep status lighting distinct from InfoLight and appliance-provided enums."""
    mode = next(
        item
        for item in DISHCARE_ENTITY_DESCRIPTIONS["select"]
        if item.key == "select_dishwasher_interior_light_mode"
    )
    status = next(
        item
        for item in DISHCARE_ENTITY_DESCRIPTIONS["switch"]
        if item.key == "switch_dishwasher_gap_illumination"
    )
    assert mode.entity == "Dishcare.Dishwasher.Setting.InteriorLightMode"
    assert mode.has_state_translation
    assert mode.options is None
    assert status.entity == "Dishcare.Dishwasher.Setting.GapIllumination"
    for description in (mode, status):
        assert description.entity_category is EntityCategory.CONFIG
        assert not description.entity_registry_enabled_default


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON keys rather than silently accepting the last value."""
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate translation key: {key}"
        result[key] = value
    return result


def test_new_features_translated_in_every_available_language() -> None:
    """All new UI labels, enum values and action fields have translations."""
    for path in TRANSLATIONS.glob("*.json"):
        data = json.loads(path.read_text(), object_pairs_hook=_unique_pairs)
        selects = data["entity"]["select"]
        for key, expected in (
            ("select_oven_steam_assist_level", {"off", "low", "high"}),
            ("select_oven_water_hardness", {"softened", "soft", "medium", "hard", "veryhard"}),
            ("select_dishwasher_interior_light_mode", {"applianceondooropen", "alwaysondooropen"}),
        ):
            assert selects[key]["name"], path.name
            assert set(selects[key]["state"]) == expected, path.name
            assert all(selects[key]["state"].values()), path.name
        for key in ("switch_freezer_auto_super", "switch_dishwasher_gap_illumination"):
            assert data["entity"]["switch"][key]["name"], path.name
        service = data["services"]["start_program_with_options"]
        assert service["name"], path.name
        assert service["description"], path.name
        assert set(service["fields"]) == {"device_id", "program", "options"}, path.name
        for field in service["fields"].values():
            assert field["name"], path.name
            assert field["description"], path.name
