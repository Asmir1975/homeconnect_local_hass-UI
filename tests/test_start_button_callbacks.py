"""Regression tests for generated start-button callbacks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from custom_components.homeconnect_ws import HCData
from custom_components.homeconnect_ws.button import HCStartButton
from custom_components.homeconnect_ws.entity_descriptions.common import generate_start_button

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeconnect_websocket.testutils import MockAppliance

ACTIVE_PROGRAM = "BSH.Common.Root.ActiveProgram"
SELECTED_PROGRAM = "BSH.Common.Root.SelectedProgram"


@pytest.fixture
def start_button_data(mock_appliance: MockAppliance) -> HCData:
    """Expose the fixture's program roots under their production names."""
    mock_appliance.entities[ACTIVE_PROGRAM] = mock_appliance.entities["Test.ActiveProgram"]
    mock_appliance.entities[SELECTED_PROGRAM] = mock_appliance.entities["Test.SelectedProgram"]
    return HCData(
        appliance=mock_appliance,
        device_info={},
        available_entity_descriptions={},
        coordinator=MagicMock(connected=True),
    )


@pytest.mark.parametrize("reset_value", [None, 0])
async def test_selected_program_updates_start_button(
    hass: HomeAssistant,
    start_button_data: HCData,
    reset_value: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Update availability on selection changes without losing access checks."""
    appliance = start_button_data.appliance
    active_program = appliance.entities[ACTIVE_PROGRAM]
    selected_program = appliance.entities[SELECTED_PROGRAM]
    button = HCStartButton(generate_start_button(appliance), start_button_data)
    button.hass = hass
    rendered: list[bool] = []
    monkeypatch.setattr(button, "async_write_ha_state", lambda: rendered.append(button.available))
    await button.async_added_to_hass()
    try:
        assert not button.available
        await selected_program.update({"value": 500})
        await appliance._task_manager.block_till_done()
        assert rendered == [True]

        await active_program.update({"access": "read"})
        await appliance._task_manager.block_till_done()
        await active_program.update({"access": "readwrite"})
        await appliance._task_manager.block_till_done()
        assert rendered == [True, False, True]

        await selected_program.update({"value": reset_value})
        await appliance._task_manager.block_till_done()
        assert rendered == [True, False, True, False]
    finally:
        await button.async_will_remove_from_hass()

    assert button.callback not in active_program._callbacks
    assert button.callback not in selected_program._callbacks
    appliance.session.send_sync.assert_not_awaited()


@pytest.mark.parametrize("selected_root_present", [True, False])
async def test_start_button_only_subscribes_to_existing_roots(
    hass: HomeAssistant,
    start_button_data: HCData,
    *,
    selected_root_present: bool,
) -> None:
    """Preserve construction and cleanup for profiles without SelectedProgram."""
    appliance = start_button_data.appliance
    selected_program = appliance.entities[SELECTED_PROGRAM]
    if not selected_root_present:
        del appliance.entities[SELECTED_PROGRAM]
    description = generate_start_button(appliance)
    assert (SELECTED_PROGRAM in description.entities) is selected_root_present
    button = HCStartButton(description, start_button_data)
    button.hass = hass
    await button.async_added_to_hass()
    try:
        assert button.callback in appliance.entities[ACTIVE_PROGRAM]._callbacks
        assert (button.callback in selected_program._callbacks) is selected_root_present
    finally:
        await button.async_will_remove_from_hass()
    assert button.callback not in selected_program._callbacks

    for program in appliance.programs.values():
        assert button.callback not in program._callbacks
