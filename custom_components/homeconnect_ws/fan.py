"""Fan entities."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, NamedTuple

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.percentage import percentage_to_ranged_value, ranged_value_to_percentage
from homeconnect_websocket.message import Action, Message

from .const import DOMAIN
from .entity import HCEntity
from .entity_descriptions.common import POWER_OFF_STATE_NAMES
from .helpers import create_entities, error_decorator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import Entity as HcEntity

    from . import HCConfigEntry, HCData
    from .entity_descriptions.descriptions_definitions import HCFanEntityDescription

PARALLEL_UPDATES = 0

_OPERATION_STATE_ENTITY = "BSH.Common.Status.OperationState"
_INACTIVE_OPERATION_STATES = frozenset({"inactive", "ready"})
_POWER_STATE_ENTITY = "BSH.Common.Setting.PowerState"


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

    def __init__(
        self,
        entity_description: HCFanEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
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
        return self.percentage is not None and self.percentage > 0

    @property
    def percentage(self) -> int | None:
        for speed in self._speed_mapping:
            if self._speed_entities[speed.entity_name].value_raw == speed.entity_value:
                return ranged_value_to_percentage(self._speed_range, speed.speed)
        return 0

    @error_decorator
    async def async_set_percentage(self, percentage: int) -> None:
        new_speed = math.ceil(percentage_to_ranged_value(self._speed_range, percentage))
        new_speed_entity: str = None
        new_speed_value: int = None
        for speed in self._speed_mapping:
            if speed.speed == new_speed:
                new_speed_entity = speed.entity_name
                new_speed_value = speed.entity_value
        if new_speed_entity or new_speed == 0:
            data = []
            for entity in self._speed_entities.values():
                if entity.name == new_speed_entity:
                    data.append({"uid": entity.uid, "value": new_speed_value})
                else:
                    data.append({"uid": entity.uid, "value": 0})
            message = Message(
                resource="/ro/values",
                action=Action.POST,
                data=data,
            )
            await self._runtime_data.appliance.session.send_sync(message)
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="speed_invalid",
                translation_placeholders={"percentage", percentage},
            )

    @error_decorator
    async def async_turn_off(self, **kwargs: Any) -> None:
        # Writing 0 to the speed options is rejected by some hoods: the appliance
        # echoes the option back at its old, non-zero value instead of accepting
        # 0 (confirmed live via debug log, vemboy200/homeconnect_local_hass#17).
        # Powering the appliance off is the confirmed working stop for those
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
