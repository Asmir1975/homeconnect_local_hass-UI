"""Fan entities."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_call_later
from homeassistant.util.percentage import percentage_to_ranged_value, ranged_value_to_percentage
from homeconnect_websocket.message import Action, Message

from .const import DOMAIN
from .entity import HCEntity
from .entity_descriptions.common import POWER_OFF_STATE_NAMES
from .helpers import create_entities, error_decorator, fill_full_option_set

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import CALLBACK_TYPE, HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import Entity as HcEntity

    from . import HCConfigEntry, HCData
    from .entity_descriptions.descriptions_definitions import HCFanEntityDescription

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_OPERATION_STATE_ENTITY = "BSH.Common.Status.OperationState"
_INACTIVE_OPERATION_STATES = frozenset({"inactive", "ready"})
_POWER_STATE_ENTITY = "BSH.Common.Setting.PowerState"
_VENTING_BOOST_ENTITY = "Cooking.Common.Option.Hood.Boost"

PRESET_NONE = "None"
PRESET_BOOST = "Boost"
PRESET_MODES: Final = [PRESET_NONE, PRESET_BOOST]

# The appliance doesn't confirm a boost start/stop right away, and reverts boost on
# its own once its own timer elapses with no "still pending" signal in between
# (ported from vemboy200/homeconnect_local_hass PR #55's discussion) - preset_mode
# below always reads the appliance's own live Boost value, this is just how long a
# just-requested change is shown immediately rather than waiting on that.
_OPTIMISTIC_PRESET_DURATION = 8


class SpeedMapping(NamedTuple):
    """Mapping of entity name / value and speed."""

    entity_name: str
    entity_value: int
    speed: int


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entites: AddEntitiesCallback,
) -> None:
    """Set up fan platform."""
    entities = create_entities({"fan": HCFan}, config_entry.runtime_data)
    async_add_entites(entities)


class HCFan(HCEntity, FanEntity):
    """Fan Entity."""

    entity_description: HCFanEntityDescription
    _speed_entities: dict[str, HcEntity] | None = None
    _speed_range: range = None
    _speed_mapping: list[SpeedMapping]
    _venting_boost_entity: HcEntity | None = None
    _optimistic_preset_mode: str | None = None
    _optimistic_preset_clear: CALLBACK_TYPE | None = None

    def __init__(
        self,
        entity_description: HCFanEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
        if entity_description.default_program is None:
            msg = "HCFanEntityDescription.default_program is required"
            raise ValueError(msg)
        self._attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_OFF
        self._speed_mapping = []
        self._speed_entities = {}
        self._attr_speed_count = 0
        for entity_name in entity_description.entities:
            entity = self._runtime_data.appliance.entities[entity_name]
            self._speed_entities[entity_name] = entity
            for option in entity.enum:
                if option != 0:
                    self._attr_speed_count += 1
                    self._speed_mapping.append(
                        SpeedMapping(
                            entity_name=entity_name,
                            entity_value=option,
                            speed=self._attr_speed_count,
                        )
                    )

        self._speed_range = (1, self._attr_speed_count)

        # OperationState changes must reach this entity's callback too, or is_on
        # below goes stale until an unrelated update fires.
        operation_state = self._runtime_data.appliance.entities.get(_OPERATION_STATE_ENTITY)
        if operation_state is not None and operation_state not in self._entities:
            self._entities.append(operation_state)

        self._venting_boost_entity = self._runtime_data.appliance.options.get(_VENTING_BOOST_ENTITY)
        if self._venting_boost_entity is not None:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = PRESET_MODES
            # Boost changes (own request or the appliance's own timer expiring)
            # must reach this entity's callback too, same reasoning as OperationState above.
            if self._venting_boost_entity not in self._entities:
                self._entities.append(self._venting_boost_entity)

    async def async_will_remove_from_hass(self) -> None:
        if self._optimistic_preset_clear is not None:
            self._optimistic_preset_clear()
        await super().async_will_remove_from_hass()

    @property
    def preset_mode(self) -> str | None:
        # Optimistic first: bridges the gap until the appliance confirms a
        # just-requested boost start/stop, or until it reverts boost on its own
        # once the boost timer elapses - see _OPTIMISTIC_PRESET_DURATION above.
        if self._optimistic_preset_mode is not None:
            return self._optimistic_preset_mode
        if self._venting_boost_entity is None:
            return None
        return PRESET_BOOST if self._venting_boost_entity.value_raw else PRESET_NONE

    @callback
    def _set_optimistic_preset(self, preset_mode: str) -> None:
        """Show `preset_mode` immediately, then defer back to the live value above."""
        if self._optimistic_preset_clear is not None:
            self._optimistic_preset_clear()
        self._optimistic_preset_mode = preset_mode
        self._optimistic_preset_clear = async_call_later(
            self.hass, _OPTIMISTIC_PRESET_DURATION, self._clear_optimistic_preset
        )
        self.async_write_ha_state()

    @callback
    def _clear_optimistic_preset(self, _now: datetime) -> None:
        self._optimistic_preset_mode = None
        self._optimistic_preset_clear = None
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        # Some hoods keep reporting a non-zero venting level after being switched
        # off. OperationState is the authoritative signal in that case.
        operation_state = self._runtime_data.appliance.entities.get(_OPERATION_STATE_ENTITY)
        if (
            operation_state is not None
            and str(operation_state.value or "").lower() in _INACTIVE_OPERATION_STATES
        ):
            return False
        return self._raw_percentage() > 0

    def _raw_percentage(self) -> int:
        for speed in self._speed_mapping:
            if self._speed_entities[speed.entity_name].value_raw == speed.entity_value:
                return ranged_value_to_percentage(self._speed_range, speed.speed)
        return 0

    @property
    def percentage(self) -> int | None:
        # Keep the reported speed in sync with is_on: once OperationState says
        # off, a stale non-zero speed value must not leave the percentage
        # attribute out of sync with the state.
        if not self.is_on:
            return 0
        return self._raw_percentage()

    @error_decorator
    async def async_set_percentage(self, percentage: int) -> None:
        # Our fan has no separate TURN_ON/async_turn_on (it turns on via a non-zero
        # percentage instead); this is the equivalent point to vemboy's
        # async_turn_on reset for "boost display shouldn't survive a manual speed
        # change or an explicit off".
        if self._venting_boost_entity is not None:
            self._set_optimistic_preset(PRESET_NONE)

        new_speed = math.ceil(percentage_to_ranged_value(self._speed_range, percentage))
        if new_speed == 0:
            await self.async_turn_off()
            return

        new_speed_entity: str | None = None
        new_speed_value: int | None = None
        for speed in self._speed_mapping:
            if speed.speed == new_speed:
                new_speed_entity = speed.entity_name
                new_speed_value = speed.entity_value
        if new_speed_entity is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="speed_invalid",
                translation_placeholders={"percentage": str(percentage)},
            )

        # Speed options are children of a Program; writing them via /ro/values
        # is rejected once no program is active. /ro/activeProgram
        # (Program.start) is the correct resource regardless of whether a
        # program is already running.
        program = self._runtime_data.appliance.programs[self.entity_description.default_program]
        options = {
            entity.uid: (new_speed_value if entity.name == new_speed_entity else 0)
            for entity in self._speed_entities.values()
        }
        if program.full_option_set:
            fill_full_option_set(program, options)

        await program.start(options, override_options=True)

    @error_decorator
    async def async_turn_off(self, **kwargs: Any) -> None:
        # Writing 0 to the speed options is rejected by some hoods: the appliance
        # echoes the option back at its old, non-zero value instead of accepting
        # 0. Powering the appliance off is the confirmed working stop for those
        # devices, so prefer it when available; keep the zero-write as a
        # fallback for appliances without a switchable PowerState so nothing
        # that works today regresses.
        power_state = self._runtime_data.appliance.entities.get(_POWER_STATE_ENTITY)
        off_value = None
        if power_state is not None:
            if power_state.min is not None and power_state.max is not None:
                # Some appliances declare a wider enum than they actually allow
                # writing, matching generate_power_switch's own settable-range
                # check for this same entity.
                settable = {
                    value
                    for key, value in (power_state.enum or {}).items()
                    if power_state.min <= key <= power_state.max
                }
            else:
                settable = set((power_state.enum or {}).values())
            off_value = next((name for name in POWER_OFF_STATE_NAMES if name in settable), None)

        if self._venting_boost_entity is not None:
            self._set_optimistic_preset(PRESET_NONE)

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

    @error_decorator
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if self._attr_preset_modes is None or preset_mode not in self._attr_preset_modes:
            _LOGGER.warning("Preset mode %s is not valid for fan.", preset_mode)
            return

        if preset_mode == PRESET_NONE:
            await self._stop_boost()
        elif preset_mode == PRESET_BOOST:
            await self._start_boost()
        self._set_optimistic_preset(preset_mode)

    async def _start_boost(self) -> None:
        # Reset every configured speed option to 0 (same entities as normal speed
        # writes) and set Boost - mirrors what the appliance itself does once its
        # own boost timer elapses (falls back to the option's pre-boost value).
        program = self._runtime_data.appliance.programs[self.entity_description.default_program]
        options: dict[int, str | int | bool] = {
            entity.uid: 0 for entity in self._speed_entities.values()
        }
        options[self._venting_boost_entity.uid] = True
        await program.start(options, override_options=True)

    async def _stop_boost(self) -> None:
        program = self._runtime_data.appliance.programs[self.entity_description.default_program]
        await program.start({}, override_options=True)
