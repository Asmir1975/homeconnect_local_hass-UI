"""Tests for select entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.exceptions import ServiceValidationError
from homeconnect_websocket.entities import Access, Execution
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

    state = hass.states.get("select.fake_brand_homeappliance_select")
    assert state
    assert state.name == "Fake_brand HomeAppliance Select"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Select"
    assert state.attributes[ATTR_OPTIONS] == ["Option1", "Option2", "Option3"]

    state = hass.states.get("select.fake_brand_homeappliance_select_translated")
    assert state
    assert state.name == "Fake_brand HomeAppliance Select.Translated"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Select.Translated"
    assert state.attributes[ATTR_OPTIONS] == ["option1", "option2", "option3"]

    state = hass.states.get("select.fake_brand_homeappliance_select_options")
    assert state
    assert state.name == "Fake_brand HomeAppliance Select.Options"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance Select.Options"
    assert state.attributes[ATTR_OPTIONS] == ["option2"]

    state = hass.states.get("select.fake_brand_homeappliance_selectedprogram")
    assert state
    assert state.name == "Fake_brand HomeAppliance SelectedProgram"
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Fake_brand HomeAppliance SelectedProgram"
    assert state.attributes[ATTR_OPTIONS] == [
        "Named Favorite",
        "favorite_002",
        "test_program_program1",
        "test_program_program2",
        "test_program_program3",
        "test_program_program4",
    ]


async def test_update(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating entity."""
    entity_id = "select.fake_brand_homeappliance_select"
    entity_id_translated = "select.fake_brand_homeappliance_select_translated"
    entity_id_options = "select.fake_brand_homeappliance_select_options"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await mock_appliance.entities["Test.Select"].update({"value": 0})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Option1"

    state = hass.states.get(entity_id_translated)
    assert state.state == "option1"

    state = hass.states.get(entity_id_options)
    assert state.state == STATE_UNKNOWN

    await mock_appliance.entities["Test.Select"].update({"value": 1})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Option2"

    state = hass.states.get(entity_id_translated)
    assert state.state == "option2"

    state = hass.states.get(entity_id_options)
    assert state.state == "option2"


async def test_select(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test selecting an option."""
    entity_id = "select.fake_brand_homeappliance_select"
    entity_id_translated = "select.fake_brand_homeappliance_select_translated"
    entity_id_options = "select.fake_brand_homeappliance_select_options"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_OPTION: "Option3",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 203, "value": 2},
        )
    )
    mock_appliance.session.send_sync.reset_mock()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id_translated,
            ATTR_OPTION: "option3",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 203, "value": 2},
        )
    )
    mock_appliance.session.send_sync.reset_mock()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id_options,
            ATTR_OPTION: "option2",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 203, "value": 1},
        )
    )


async def test_select_excludes_enum_members_outside_min_max(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,  # noqa: ARG001
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """An enum member outside the entity's writable range isn't offered."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_select_minmax"

    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_OPTIONS] == ["On1", "On2"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "Off"},
            blocking=True,
        )


async def test_select_excludes_enum_members_below_min_only(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,  # noqa: ARG001
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Only a min bound is set: members below it are excluded, no upper cutoff."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_select_minonly"

    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_OPTIONS] == ["On1", "On2"]


async def test_select_excludes_enum_members_above_max_only(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,  # noqa: ARG001
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Only a max bound is set: members above it are excluded, no lower cutoff."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_select_maxonly"

    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_OPTIONS] == ["Off", "On1"]


async def test_select_min_max_translated_write_and_reject(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Translated select: excluded option rejected, allowed option written."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_select_minmax_translated"

    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_OPTIONS] == ["on1", "on2"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "off"},
            blocking=True,
        )

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "on1"},
        blocking=True,
    )
    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 209, "value": 1},
        )
    )


async def test_update_program(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating program select entity."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    await mock_appliance.entities["Test.SelectedProgram"].update({"value": 500})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "test_program_program1"

    await mock_appliance.entities["Test.SelectedProgram"].update({"value": 502})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Named Favorite"


async def test_update_program_from_active_program(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test updating program select entity from the active program."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    await mock_appliance.entities["Test.ActiveProgram"].update({"value": 501})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "test_program_program2"


async def test_start_only_program_available_with_read_only_selected_program(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test selecting start-only programs when SelectedProgram is read-only."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    await mock_appliance.entities["Test.SelectedProgram"].update({"access": Access.READ})
    for program in mock_appliance.programs.values():
        await program.update({"execution": Execution.START_ONLY})
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    state = hass.states.get(entity_id)
    assert state.state == STATE_UNKNOWN

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_OPTION: "test_program_program2",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/activeProgram",
            action=Action.POST,
            data={"program": 501, "options": []},
        )
    )


async def test_start_only_full_option_set(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """A full-option-set START_ONLY program must fill options, not send an empty set."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_OPTION: "test_program_program4",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/activeProgram",
            action=Action.POST,
            data={
                "program": 505,
                "options": [
                    {"uid": 403, "value": 0},
                    {"uid": 404, "value": 0},
                    {"uid": 506, "value": 1},
                ],
            },
        )
    )


async def test_start_only_availability_follows_program_execution_updates(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """
    Test a pure Program.execution update reaches this entity's HA state.

    Access.READ alone is now always available via is_locked_option(), so this
    fallback only still matters for Access.NONE (SelectedProgram inapplicable,
    e.g. no program selected yet). The read-only-SelectedProgram fallback reads
    Program.execution/available for every mapped program, but only
    ActiveProgram was subscribed for callbacks. A program flipping to
    START_ONLY without any SelectedProgram/ActiveProgram value change must
    still refresh availability, not just future unrelated updates.
    """
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    await mock_appliance.entities["Test.SelectedProgram"].update({"access": Access.NONE})
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    # Only Program3 defaults to START_ONLY; the two Program*/Favorite* entries
    # don't, so the fallback condition (all mapped programs START_ONLY) isn't
    # met yet even though Program3 alone already qualifies.
    state = hass.states.get(entity_id)
    assert state.state == STATE_UNAVAILABLE

    for name in (
        "Test.Program.Program1",
        "Test.Program.Program2",
        "BSH.Common.Program.Favorite.001",
        "BSH.Common.Program.Favorite.002",
    ):
        await mock_appliance.programs[name].update({"execution": Execution.START_ONLY})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state != STATE_UNAVAILABLE


async def test_select_program(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test selecting an program."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_OPTION: "test_program_program2",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/selectedProgram",
            action=Action.POST,
            data={
                "program": 501,
                "options": [],
            },
        )
    )

    mock_appliance.session.send_sync.reset_mock()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_OPTION: "test_program_program3",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/activeProgram",
            action=Action.POST,
            data={
                "program": 502,
                "options": [{"uid": 401, "value": None}, {"uid": 402, "value": None}],
            },
        )
    )


async def test_select_program_preserves_required_full_option_set(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Programs declaring fullOptionSet keep the existing merged payload."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    program = mock_appliance.programs["Test.Program.Program2"]
    program._full_option_set = True
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_OPTION: "test_program_program2",
        },
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/selectedProgram",
            action=Action.POST,
            data={
                "program": 501,
                "options": [{"uid": 401, "value": None}, {"uid": 402, "value": None}],
            },
        )
    )


async def test_selected_program_read_write_read_read_write_sequence(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """SelectedProgram stays available and readonly across a Delayed Start lock/unlock."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    await mock_appliance.entities["Test.SelectedProgram"].update({"value": 500})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "test_program_program1"
    assert state.attributes["readonly"] is False

    await mock_appliance.entities["Test.SelectedProgram"].update({"access": Access.READ})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state != STATE_UNAVAILABLE
    assert state.state == "test_program_program1"
    assert state.attributes["readonly"] is True

    await mock_appliance.entities["Test.SelectedProgram"].update({"access": Access.READ_WRITE})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "test_program_program1"
    assert state.attributes["readonly"] is False


async def test_select_program_raises_when_selected_program_locked(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Selecting a SELECT_ONLY/SELECT_AND_START program raises while SelectedProgram is locked."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    await mock_appliance.entities["Test.SelectedProgram"].update({"access": Access.READ})
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {
                ATTR_ENTITY_ID: entity_id,
                ATTR_OPTION: "test_program_program1",
            },
            blocking=True,
        )

    mock_appliance.session.send_sync.assert_not_awaited()


async def test_selected_program_unavailable_when_access_none(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """SelectedProgram stays unavailable when Access.NONE, unlike Access.READ."""
    entity_id = "select.fake_brand_homeappliance_selectedprogram"
    await mock_appliance.entities["Test.SelectedProgram"].update({"access": Access.NONE})
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    state = hass.states.get(entity_id)
    assert state.state == STATE_UNAVAILABLE


async def test_favorite_name_arrives_after_setup(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """The appliance sends favorite names after setup, select and sensor follow."""
    select_id = "select.fake_brand_homeappliance_selectedprogram"
    sensor_id = "sensor.fake_brand_homeappliance_activeprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    await mock_appliance.entities["Test.ActiveProgram"].update({"value": 503})
    await hass.async_block_till_done()
    assert "favorite_002" in hass.states.get(select_id).attributes[ATTR_OPTIONS]
    assert hass.states.get(sensor_id).state == "favorite_002"

    favorite = mock_appliance.settings["BSH.Common.Setting.Favorite.002.Name"]
    for name in ("Late Name", "Renamed", ""):
        await favorite.update({"value": name})
        await hass.async_block_till_done()
        expected = name or "favorite_002"
        assert expected in hass.states.get(select_id).attributes[ATTR_OPTIONS]
        assert expected in hass.states.get(sensor_id).attributes[ATTR_OPTIONS]
        assert hass.states.get(sensor_id).state == expected

    await favorite.update({"value": "Late Name"})
    await hass.async_block_till_done()
    mock_appliance.session.send_sync.reset_mock()
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: select_id, ATTR_OPTION: "Late Name"},
        blocking=True,
    )
    message = mock_appliance.session.send_sync.call_args.args[0]
    assert message.data["program"] == 503


async def test_duplicate_favorite_names_select_the_right_slot(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Two favorites with the same name stay separately selectable."""
    select_id = "select.fake_brand_homeappliance_selectedprogram"
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    await mock_appliance.settings["BSH.Common.Setting.Favorite.001.Name"].update(
        {"value": "Milchschaum"}
    )
    await mock_appliance.settings["BSH.Common.Setting.Favorite.002.Name"].update(
        {"value": "Milchschaum"}
    )
    await hass.async_block_till_done()
    options = hass.states.get(select_id).attributes[ATTR_OPTIONS]
    assert "Milchschaum (001)" in options
    assert "Milchschaum (002)" in options
    assert "Milchschaum" not in options

    mock_appliance.session.send_sync.reset_mock()
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: select_id, ATTR_OPTION: "Milchschaum (001)"},
        blocking=True,
    )
    assert mock_appliance.session.send_sync.call_args.args[0].data["program"] == 502
    mock_appliance.session.send_sync.reset_mock()
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: select_id, ATTR_OPTION: "Milchschaum (002)"},
        blocking=True,
    )
    assert mock_appliance.session.send_sync.call_args.args[0].data["program"] == 503


async def test_hood_level_select_setup(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,  # noqa: ARG001
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Test the always-visible Hood level Select."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)

    state = hass.states.get("select.fake_brand_homeappliance_hoodlevel")
    assert state
    assert state.state == "Off"
    assert state.attributes[ATTR_OPTIONS] == [
        "Off",
        "FanStage01",
        "FanStage02",
        "IntensiveStage1",
        "Boost",
    ]


async def test_hood_level_select_venting(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Selecting a venting level starts the owning Program, zeroing Intensive."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_hoodlevel"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "FanStage02"},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/activeProgram",
            action=Action.POST,
            data={
                "program": 522,
                "options": [{"uid": 520, "value": 2}, {"uid": 521, "value": 0}],
            },
        )
    )

    await mock_appliance.entities["Test.HoodLevelVenting"].update({"value": 2})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "FanStage02"


async def test_hood_level_select_intensive_zeroes_venting(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Selecting an intensive level zeroes the venting option."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_hoodlevel"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "IntensiveStage1"},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/activeProgram",
            action=Action.POST,
            data={
                "program": 522,
                "options": [{"uid": 520, "value": 0}, {"uid": 521, "value": 1}],
            },
        )
    )


async def test_hood_level_select_off_uses_power_state(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Selecting Off powers the appliance down instead of zeroing both options."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_hoodlevel"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "Off"},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/values",
            action=Action.POST,
            data={"uid": 205, "value": 1},
        )
    )


async def test_hood_level_select_shows_boost(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Boost zeroes both speed options; current_option must show Boost, not Off."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_hoodlevel"
    assert "Boost" in hass.states.get(entity_id).attributes[ATTR_OPTIONS]

    await mock_appliance.entities["Cooking.Common.Option.Hood.Boost"].update({"value": True})
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "Boost"

    await mock_appliance.entities["Cooking.Common.Option.Hood.Boost"].update({"value": False})
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "Off"


async def test_hood_level_select_boost_sends_expected_payload(
    hass: HomeAssistant,
    mock_appliance: MockAppliance,
    patch_entity_description: None,  # noqa: ARG001
) -> None:
    """Selecting Boost zeroes both speed options and sets Boost in one write."""
    assert await setup_config_entry(hass, MOCK_CONFIG_DATA)
    entity_id = "select.fake_brand_homeappliance_hoodlevel"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "Boost"},
        blocking=True,
    )

    mock_appliance.session.send_sync.assert_awaited_once_with(
        Message(
            resource="/ro/activeProgram",
            action=Action.POST,
            data={
                "program": 522,
                "options": [
                    {"uid": 520, "value": 0},
                    {"uid": 521, "value": 0},
                    {"uid": 508, "value": True},
                ],
            },
        )
    )
