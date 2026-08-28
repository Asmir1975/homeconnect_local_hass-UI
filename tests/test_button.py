"""Tests for button entity."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from custom_components.homeconnect_ws import coordinator
from custom_components.homeconnect_ws.const import DOMAIN
from custom_components.homeconnect_ws.entity_descriptions.common import generate_start_button
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, ATTR_FRIENDLY_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from homeconnect_websocket.message import Action, Message
from homeconnect_websocket.testutils import MockAppliance

from . import setup_config_entry
from .const import DEVICE_DESCRIPTION, MOCK_CONFIG_DATA

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_setup(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,  # noqa: ARG001
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test setting up entity."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    state = hass.states.get("button.fake_brand_homeappliance_activeprogram")
    assert state
    assert state.name == "Fake_brand HomeAppliance ActiveProgram"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance ActiveProgram"

    state = hass.states.get("button.fake_brand_homeappliance_abortprogram")
    assert state
    assert state.name == "Fake_brand HomeAppliance AbortProgram"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance AbortProgram"


async def test_start(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test pressing start button."""
    entity_id = "button.fake_brand_homeappliance_activeprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    await mock_appliance.entities["Test.SelectedProgram"].update({"value": 500})
    await hass.async_block_till_done()

    await hass.services.async_call(
        domain=BUTTON_DOMAIN,
        service=SERVICE_PRESS,
        service_data={ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/activeProgram",
            action=Action.POST,
            data={
                "program": 500,
                "options": [{"uid": 401, "value": None}, {"uid": 402, "value": None}],
            },
        )
    )


async def test_abort(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test pressing abort button."""
    entity_id = "button.fake_brand_homeappliance_abortprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        domain=BUTTON_DOMAIN,
        service=SERVICE_PRESS,
        service_data={ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 300, "value": True},
        )
    )


ACTIVE_PROGRAM = "BSH.Common.Root.ActiveProgram"
SELECTED_PROGRAM = "BSH.Common.Root.SelectedProgram"


@pytest.fixture
def pending_program_appliance(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> MockAppliance:
    """Build a profile with execution unavailable until the handshake."""
    description = deepcopy(DEVICE_DESCRIPTION)
    description["activeProgram"]["name"] = ACTIVE_PROGRAM
    description["selectedProgram"]["name"] = SELECTED_PROGRAM
    for program in description["program"]:
        program["execution"] = getattr(request, "param", "none")
    appliance = MockAppliance(description, "host", "mock_app", "mock_app_id", "PSK_KEY")
    appliance.session.connected = True
    monkeypatch.setattr(coordinator, "HomeAppliance", Mock(return_value=appliance))
    monkeypatch.setattr(coordinator.HomeConnectCoordinator, "connected", True)
    return appliance


def test_create_start_button_before_execution_is_known(
    pending_program_appliance: MockAppliance,
) -> None:
    """A NONE profile must not permanently lose its start button at setup."""
    description = generate_start_button(pending_program_appliance)
    assert description is not None
    assert description.key == "button_start_program"
    assert description.entity == ACTIVE_PROGRAM


async def test_execution_update_refreshes_start_button(
    hass: HomeAssistant,
    pending_program_appliance: MockAppliance,
) -> None:
    """Refresh HA state when only the selected program execution changes."""
    appliance = pending_program_appliance
    await appliance.entities[SELECTED_PROGRAM].update({"value": 500})
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{appliance.info['deviceID']}-button_start_program"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    await appliance.programs["Test.Program.Program1"].update({"execution": "SELECTANDSTART"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNKNOWN


@pytest.mark.parametrize("pending_program_appliance", ["none", "selectandstart"], indirect=True)
@pytest.mark.parametrize("blocked_execution", ["none", "startonly", "selectonly"])
async def test_execution_changes_preserve_start_restrictions(
    hass: HomeAssistant,
    pending_program_appliance: MockAppliance,
    blocked_execution: str,
) -> None:
    """Execution updates must not bypass access or start unsupported modes."""
    appliance = pending_program_appliance
    program = appliance.programs["Test.Program.Program1"]
    await appliance.entities[SELECTED_PROGRAM].update({"value": 500})
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{appliance.info['deviceID']}-button_start_program"
    )
    assert entity_id is not None
    await program.update({"execution": "selectandstart"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    await program.update({"execution": blocked_execution})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    await program.update({"execution": "selectandstart"})
    await appliance.entities[ACTIVE_PROGRAM].update({"access": "read"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    await appliance.entities[ACTIVE_PROGRAM].update({"access": "readwrite"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    assert all(
        request.args[0].action == Action.GET
        for request in appliance.session.send_sync.await_args_list
    )


async def test_selected_program_changes_after_initial_none(
    hass: HomeAssistant,
    pending_program_appliance: MockAppliance,
) -> None:
    """Follow the newly selected program and preserve connection checks."""
    appliance = pending_program_appliance
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{appliance.info['deviceID']}-button_start_program"
    )
    assert entity_id is not None
    await appliance.programs["Test.Program.Program1"].update({"execution": "selectandstart"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    await appliance.entities[SELECTED_PROGRAM].update({"value": 500})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    await appliance.entities[SELECTED_PROGRAM].update({"value": 501})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    await appliance.programs["Test.Program.Program2"].update({"execution": "selectandstart"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    entry.runtime_data.coordinator.connected = False
    appliance.session.connected = False
    entry.runtime_data.coordinator.async_set_updated_data(None)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    appliance.session.connected = True
    await appliance.programs["Test.Program.Program2"].update({"execution": "selectandstart"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    await appliance.entities[SELECTED_PROGRAM].update({"value": 0})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert all(
        request.args[0].action == Action.GET
        for request in appliance.session.send_sync.await_args_list
    )


async def test_execution_callbacks_survive_reload(
    hass: HomeAssistant,
    pending_program_appliance: MockAppliance,
) -> None:
    """Keep the same entity and working callbacks after unloading and reloading."""
    appliance = pending_program_appliance
    await appliance.entities[SELECTED_PROGRAM].update({"value": 500})
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    registry = er.async_get(hass)
    unique_id = f"{appliance.info['deviceID']}-button_start_program"
    entity_id = registry.async_get_entity_id("button", DOMAIN, unique_id)
    assert entity_id is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await appliance.programs["Test.Program.Program1"].update({"execution": "selectandstart"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) == entity_id
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    await appliance.programs["Test.Program.Program1"].update({"execution": "none"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert all(
        request.args[0].action == Action.GET
        for request in appliance.session.send_sync.await_args_list
    )


@pytest.mark.parametrize("missing_root", [ACTIVE_PROGRAM, SELECTED_PROGRAM])
def test_none_profile_requires_program_roots(
    pending_program_appliance: MockAppliance,
    missing_root: str,
) -> None:
    """Do not add a new NONE button whose backing program root is missing."""
    del pending_program_appliance.entities[missing_root]
    assert generate_start_button(pending_program_appliance) is None


@pytest.mark.parametrize("pending_program_appliance", ["startonly", "selectonly"], indirect=True)
def test_no_button_for_unsupported_execution(
    pending_program_appliance: MockAppliance,
) -> None:
    """Keep START_ONLY and SELECT_ONLY profiles outside the new creation path."""
    assert generate_start_button(pending_program_appliance) is None


def test_no_button_without_programs(pending_program_appliance: MockAppliance) -> None:
    """An appliance with no programs still has no start button."""
    pending_program_appliance.programs.clear()
    assert generate_start_button(pending_program_appliance) is None


@pytest.mark.parametrize("pending_program_appliance", ["none", "selectandstart"], indirect=True)
async def test_read_only_hob_start_stays_disabled(
    hass: HomeAssistant,
    pending_program_appliance: MockAppliance,
) -> None:
    """The new NONE creation path must preserve the read-only hob exception."""
    appliance = pending_program_appliance
    appliance.info["type"] = "Hob"
    await appliance.entities[ACTIVE_PROGRAM].update({"access": "read"})
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{appliance.info['deviceID']}-button_start_program"
    )
    assert entity_id is not None
    assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
