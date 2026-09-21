"""Tests for the favorite filter option."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.homeconnect_ws.const import CONF_FILTER_UNSAVED_FAVORITES, DOMAIN
from homeassistant.components.select import ATTR_OPTIONS
from homeassistant.data_entry_flow import FlowResultType
from homeconnect_websocket.entities import Setting
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import setup_config_entry
from .const import MOCK_CONFIG_DATA

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeconnect_websocket.testutils import MockAppliance

SELECT_ID = "select.fake_brand_homeappliance_selectedprogram"
SENSOR_ID = "sensor.fake_brand_homeappliance_activeprogram"


async def test_options_default_and_preserve(hass: HomeAssistant) -> None:
    """The filter is off by default and unrelated options are kept."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"other": "keep"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({}) == {CONF_FILTER_UNSAVED_FAVORITES: False}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_FILTER_UNSAVED_FAVORITES: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"other": "keep", CONF_FILTER_UNSAVED_FAVORITES: True}


async def _set_filter(hass: HomeAssistant, entry_id: str, *, enabled: bool) -> None:
    result = await hass.config_entries.options.async_init(entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_FILTER_UNSAVED_FAVORITES: enabled}
    )
    await hass.async_block_till_done()


async def test_filter_hides_unsaved_slots(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Switching the filter and saving or deleting a slot updates the list."""
    functionality = Setting(
        {
            "uid": 32824,
            "name": "BSH.Common.Setting.Favorite.001.Functionality",
            "enumeration": {"0": "Off", "1": "Program"},
            "access": "readwrite",
            "available": True,
            "protocolType": "Integer",
        },
        mock_appliance,
    )
    mock_appliance.settings[functionality.name] = functionality
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await functionality.update({"value": 0})
    await hass.async_block_till_done()

    options = hass.states.get(SELECT_ID).attributes[ATTR_OPTIONS]
    assert "Named Favorite" in options
    assert "favorite_002" in options

    await _set_filter(hass, entry.entry_id, enabled=True)
    options = hass.states.get(SELECT_ID).attributes[ATTR_OPTIONS]
    assert "Named Favorite" not in options
    assert "favorite_002" not in options
    assert "test_program_program1" in options
    assert "favorite_002" in hass.states.get(SENSOR_ID).attributes[ATTR_OPTIONS]

    await functionality.update({"value": 1})
    await hass.async_block_till_done()
    assert "Named Favorite" in hass.states.get(SELECT_ID).attributes[ATTR_OPTIONS]

    await functionality.update({"value": 0})
    await hass.async_block_till_done()
    assert "Named Favorite" not in hass.states.get(SELECT_ID).attributes[ATTR_OPTIONS]

    await _set_filter(hass, entry.entry_id, enabled=False)
    options = hass.states.get(SELECT_ID).attributes[ATTR_OPTIONS]
    assert "Named Favorite" in options
    assert "favorite_002" in options


async def test_filter_without_functionality_flag_uses_the_name(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Appliances that report no flag keep named slots and hide unnamed ones."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await _set_filter(hass, entry.entry_id, enabled=True)
    options = hass.states.get(SELECT_ID).attributes[ATTR_OPTIONS]
    assert "Named Favorite" in options
    assert "favorite_002" not in options

    await mock_appliance.settings["BSH.Common.Setting.Favorite.002.Name"].update(
        {"value": "Second"}
    )
    await hass.async_block_till_done()
    assert "Second" in hass.states.get(SELECT_ID).attributes[ATTR_OPTIONS]
