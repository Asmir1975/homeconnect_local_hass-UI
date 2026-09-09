"""Tests for hob favorite button events."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from custom_components.homeconnect_ws import HCData
from custom_components.homeconnect_ws.binary_sensor import HCBinarySensor
from custom_components.homeconnect_ws.entity_descriptions import get_available_entities
from homeconnect_websocket.entities import DeviceDescription, EntityDescription

if TYPE_CHECKING:
    from homeconnect_websocket.testutils import MockApplianceType


@pytest.mark.parametrize("favorites", [(), ("001",), ("002",), ("001", "002")])
async def test_favorite_events(
    mock_homeconnect_appliance: MockApplianceType, favorites: tuple[str, ...]
) -> None:
    """Only create supported sensors and map both event pulses to on/off."""
    appliance = await mock_homeconnect_appliance(
        description=DeviceDescription(
            event=[
                EntityDescription(
                    uid=9000 + index,
                    name=f"BSH.Common.Event.Favorite.{favorite}.ExternalTrigger",
                    enumeration={"0": "Off", "1": "Present", "2": "Confirmed"},
                )
                for index, favorite in enumerate(favorites)
            ]
        )
    )
    appliance.info = {"deviceID": "test_device_id"}
    available = get_available_entities(appliance)
    descriptions = [
        item
        for item in available["binary_sensor"]
        if item.key.startswith("binary_sensor_favorite_")
    ]
    expected_keys = {
        "001": "binary_sensor_favorite_short_press",
        "002": "binary_sensor_favorite_long_press",
    }
    assert {item.key for item in descriptions} == {expected_keys[item] for item in favorites}
    runtime_data = HCData(
        appliance=appliance,
        device_info=MagicMock(),
        available_entity_descriptions=available,
        coordinator=MagicMock(),
    )
    for description in descriptions:
        favorite = next(key for key, value in expected_keys.items() if value == description.key)
        event = appliance.entities[f"BSH.Common.Event.Favorite.{favorite}.ExternalTrigger"]
        sensor = HCBinarySensor(description, runtime_data)
        for value, expected in [(0, False), (1, True), (0, False), (2, True), (0, False)]:
            await event.update({"value": value})
            assert sensor.is_on is expected
