"""Select entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeconnect_websocket.entities import Access, Execution
from homeconnect_websocket.message import Action, Message

from .const import CONF_FILTER_UNSAVED_FAVORITES
from .entity import HCEntity
from .entity_descriptions.common import POWER_OFF_STATE_NAMES
from .fan import SpeedMapping
from .helpers import (
    create_entities,
    ensure_writable,
    entity_is_available,
    error_decorator,
    fill_full_option_set,
)
from .program_names import favorite_name_settings, program_labels, selectable_program_labels

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import ActiveProgram, Program, SelectedProgram
    from homeconnect_websocket.entities import Entity as HcEntity

    from . import HCConfigEntry, HCData
    from .entity_descriptions.descriptions_definitions import (
        HCFanEntityDescription,
        HCSelectEntityDescription,
    )
PARALLEL_UPDATES = 0

_ACTIVE_PROGRAM_ACCESS = (Access.READ_WRITE, Access.WRITE_ONLY)
_SELECTED_PROGRAM_SUFFIX = ".SelectedProgram"
_OPERATION_STATE_ENTITY = "BSH.Common.Status.OperationState"
_INACTIVE_OPERATION_STATES = frozenset({"inactive", "ready"})
_POWER_STATE_ENTITY = "BSH.Common.Setting.PowerState"
HOOD_LEVEL_OFF = "Off"
HOOD_LEVEL_BOOST = "Boost"
_VENTING_BOOST_ENTITY = "Cooking.Common.Option.Hood.Boost"


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entites: AddEntitiesCallback,
) -> None:
    """Set up select platform."""
    entities = create_entities(
        {"select": HCSelect, "program": HCProgram, "hood_level": HCHoodLevelSelect},
        config_entry.runtime_data,
    )
    async_add_entites(entities)


class HCSelect(HCEntity, SelectEntity):
    """Select Entity."""

    entity_description: HCSelectEntityDescription
    _rev_options: dict[str, str]

    def __init__(
        self,
        entity_description: HCSelectEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)

        self._rev_options = {}
        if entity_description.options:
            self._attr_options = entity_description.options
            # A curated options list is independent of min/max scoping, so
            # the reverse lookup keeps covering the full device enum.
            translatable_items = self._entity.enum.items() if self._entity.enum else []
        elif self._entity.enum:
            entity_min = self._entity.min
            entity_max = self._entity.max
            # Some enum members are reported but rejected on write, e.g. an
            # "off" state outside the appliance's writable range. Excluding
            # them here, and from the reverse lookup below, keeps them from
            # being offered or written in the first place.
            writable_items = [
                (key, value)
                for key, value in self._entity.enum.items()
                if (entity_min is None or key >= entity_min)
                and (entity_max is None or key <= entity_max)
            ]
            self._attr_options = []
            if self.entity_description.has_state_translation:
                for _, value in writable_items:
                    self._attr_options.append(str(value).lower())
            else:
                for _, value in writable_items:
                    self._attr_options.append(str(value))
            translatable_items = writable_items
        else:
            translatable_items = []

        if self.entity_description.has_state_translation:
            for _, value in translatable_items:
                self._rev_options[str(value).lower()] = value

    @property
    def current_option(self) -> str:
        if self.entity_description.has_state_translation:
            value = str(self._entity.value).lower()
            if value in self._attr_options:
                return value
        value = str(self._entity.value)
        if value in self._attr_options:
            return value
        return None

    @error_decorator
    async def async_select_option(self, option: str) -> None:
        ensure_writable(self._entity)
        if self._rev_options:
            option = self._rev_options[option]
        await self._entity.set_value(option)


class HCProgram(HCSelect):
    """Program select Entity."""

    _entity: SelectedProgram
    _active_program_entity: ActiveProgram | None = None

    def __init__(
        self,
        entity_description: HCSelectEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
        self._programs = entity_description.mapping
        # Favorite names arrive after setup, observe them so the labels follow.
        self._entities.extend(
            favorite_name_settings(runtime_data.appliance, self._programs, with_functionality=True)
        )
        if entity_description.entity and entity_description.entity.endswith(
            _SELECTED_PROGRAM_SUFFIX
        ):
            active_program_entity = (
                f"{entity_description.entity.removesuffix(_SELECTED_PROGRAM_SUFFIX)}.ActiveProgram"
            )
            self._active_program_entity = runtime_data.appliance.entities.get(active_program_entity)
            if self._active_program_entity:
                self._entities.append(self._active_program_entity)
        # Program.execution/available changes must reach this entity's callback too,
        # or the available property below goes stale until an unrelated update fires.
        for name in self._programs:
            program = runtime_data.appliance.programs.get(name)
            if program is not None and program not in self._entities:
                self._entities.append(program)

    def _labels(self) -> dict[str, str]:
        if self._runtime_data.coordinator.config_entry.options.get(
            CONF_FILTER_UNSAVED_FAVORITES, False
        ):
            return selectable_program_labels(self._runtime_data.appliance, self._programs)
        return program_labels(self._runtime_data.appliance, self._programs)

    @property
    def options(self) -> list[str] | None:
        return list(self._labels().values())

    @property
    def available(self) -> bool:
        if super().available:
            return True
        conn = (
            self._runtime_data.coordinator.connected
            or self._runtime_data.appliance.session.connected
        )
        if not conn or self._active_program_entity is None:
            return False
        return (
            entity_is_available(self._active_program_entity, _ACTIVE_PROGRAM_ACCESS)
            and self._programs_are_start_only()
        )

    def _programs_are_start_only(self) -> bool:
        programs: list[Program | None] = [
            self._runtime_data.appliance.programs.get(program) for program in self._programs
        ]
        return bool(programs) and all(
            program is not None
            and program.available is not False
            and program.execution == Execution.START_ONLY
            for program in programs
        )

    @property
    def current_option(self) -> str | None:
        current_program = self._runtime_data.appliance.selected_program
        if current_program is None and self._active_program_entity is not None:
            current_program = self._runtime_data.appliance.active_program

        if current_program:
            return self._labels().get(current_program.name, current_program.name)
        return None

    @error_decorator
    async def async_select_option(self, option: str) -> None:
        program_by_label = {label: name for name, label in self._labels().items()}
        selected_program = self._runtime_data.appliance.programs[program_by_label[option]]
        if selected_program.execution in (Execution.SELECT_ONLY, Execution.SELECT_AND_START):
            # START_ONLY below writes ActiveProgram directly and has its own
            # read-only fallback; only this path actually writes SelectedProgram.
            ensure_writable(self._entity)
            # Do not carry shared option shadows from the previously selected
            # program unless this program explicitly requires a full option set.
            await selected_program.select(override_options=not selected_program.full_option_set)
        elif selected_program.execution == Execution.START_ONLY:
            if selected_program.full_option_set:
                # Some appliances validate a program write against the program's
                # complete option set and reject a partial one — true regardless
                # of whether SelectedProgram happens to be writable right now.
                options = fill_full_option_set(selected_program, {})
                await selected_program.start(options, override_options=True)
            elif entity_is_available(self._entity, self.entity_description.available_access):
                # SelectedProgram is writable, this path already worked before the
                # read-only fallback above existed. Leave its payload unchanged.
                await selected_program.start()
            else:
                # Reached only via the read-only-SelectedProgram fallback. Suppresses
                # the library's automatic READ_WRITE option shadows for this call
                # (Program._build_options); scoped to this path so devices that
                # already worked keep their existing payload.
                await selected_program.start(override_options=True)


class HCHoodLevelSelect(HCEntity, SelectEntity):
    """
    Single always-visible Hood level Select.

    Venting/Intensive are Program Options, not Settings, so this mirrors HCFan's write path
    (program.start over /ro/activeProgram, zeroing the other option,
    PowerState-off fallback for "Off") instead of the generic
    HCSelect.async_select_option()/entity.set_value(), which would write the
    wrong resource. Options are the device's own enum names, "Off" is our
    own addition since the appliance has no selectable off stage.
    """

    entity_description: HCFanEntityDescription
    _speed_entities: dict[str, HcEntity]
    _speed_mapping: list[SpeedMapping]
    _venting_boost_entity: HcEntity | None = None

    def __init__(
        self,
        entity_description: HCFanEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
        self._speed_entities = {}
        self._speed_mapping = []
        speed = 0
        for entity_name in entity_description.entities:
            entity = self._runtime_data.appliance.entities[entity_name]
            self._speed_entities[entity_name] = entity
            for option in entity.enum:
                if option != 0:
                    speed += 1
                    self._speed_mapping.append(SpeedMapping(entity_name, option, speed))
        self._attr_options = [
            HOOD_LEVEL_OFF,
            *(
                self._speed_entities[m.entity_name].enum[m.entity_value]
                for m in self._speed_mapping
            ),
        ]
        operation_state = self._runtime_data.appliance.entities.get(_OPERATION_STATE_ENTITY)
        if operation_state is not None and operation_state not in self._entities:
            self._entities.append(operation_state)

        # Boost zeroes both speed options (see HCFan._start_boost in fan.py), so
        # without this, current_option would fall through to HOOD_LEVEL_OFF while
        # the hood is actually running Boost.
        self._venting_boost_entity = self._runtime_data.appliance.options.get(_VENTING_BOOST_ENTITY)
        if self._venting_boost_entity is not None:
            self._attr_options.append(HOOD_LEVEL_BOOST)
            if self._venting_boost_entity not in self._entities:
                self._entities.append(self._venting_boost_entity)

    @property
    def current_option(self) -> str:
        operation_state = self._runtime_data.appliance.entities.get(_OPERATION_STATE_ENTITY)
        if (
            operation_state is not None
            and str(operation_state.value or "").lower() in _INACTIVE_OPERATION_STATES
        ):
            return HOOD_LEVEL_OFF
        for speed in self._speed_mapping:
            entity = self._speed_entities[speed.entity_name]
            if entity.value_raw == speed.entity_value:
                return entity.enum[speed.entity_value]
        if self._venting_boost_entity is not None and self._venting_boost_entity.value_raw:
            return HOOD_LEVEL_BOOST
        return HOOD_LEVEL_OFF

    @error_decorator
    async def async_select_option(self, option: str) -> None:
        if option == HOOD_LEVEL_OFF:
            await self._async_turn_off()
            return
        if option == HOOD_LEVEL_BOOST:
            await self._async_start_boost()
            return

        new_speed_entity: str | None = None
        new_speed_value: int | None = None
        for speed in self._speed_mapping:
            entity = self._speed_entities[speed.entity_name]
            if entity.enum[speed.entity_value] == option:
                new_speed_entity = speed.entity_name
                new_speed_value = speed.entity_value
                break

        program = self._runtime_data.appliance.programs[self.entity_description.default_program]
        options = {
            entity.uid: (new_speed_value if entity.name == new_speed_entity else 0)
            for entity in self._speed_entities.values()
        }
        if program.full_option_set:
            fill_full_option_set(program, options)

        await program.start(options, override_options=True)

    async def _async_turn_off(self) -> None:
        power_state = self._runtime_data.appliance.entities.get(_POWER_STATE_ENTITY)
        off_value = None
        if power_state is not None:
            if power_state.min is not None and power_state.max is not None:
                settable = {
                    value
                    for key, value in (power_state.enum or {}).items()
                    if power_state.min <= key <= power_state.max
                }
            else:
                settable = set((power_state.enum or {}).values())
            off_value = next((name for name in POWER_OFF_STATE_NAMES if name in settable), None)

        if off_value is not None:
            await power_state.set_value(off_value)
            return

        data = [{"uid": entity.uid, "value": 0} for entity in self._speed_entities.values()]
        message = Message(
            resource="/ro/values",
            action=Action.POST,
            data=data,
        )
        await self._runtime_data.appliance.session.send_sync(message)

    async def _async_start_boost(self) -> None:
        # Mirrors HCFan._start_boost: zero every speed option, same entities as
        # a normal level write, and set Boost.
        program = self._runtime_data.appliance.programs[self.entity_description.default_program]
        options: dict[int, str | int | bool] = {
            entity.uid: 0 for entity in self._speed_entities.values()
        }
        options[self._venting_boost_entity.uid] = True
        await program.start(options, override_options=True)
