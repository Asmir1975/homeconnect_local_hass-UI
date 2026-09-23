"""Button entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeconnect_websocket.entities import Execution

from .entity import HCEntity
from .helpers import (
    create_entities,
    error_decorator,
    fill_full_option_set,
    start_program_with_fallback,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import ActiveProgram, Command

    from . import HCConfigEntry
    from .entity_descriptions.descriptions_definitions import HCButtonEntityDescription

PARALLEL_UPDATES = 0

COFFEE_MAKER_TYPE = "CoffeeMaker"


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entites: AddEntitiesCallback,
) -> None:
    """Set up button platform."""
    entities = create_entities(
        {"button": HCButton, "start_button": HCStartButton}, config_entry.runtime_data
    )
    async_add_entites(entities)


class HCButton(HCEntity, ButtonEntity):
    """Abort Button Entity."""

    _entity: Command
    entity_description: HCButtonEntityDescription

    @error_decorator
    async def async_press(self) -> None:
        await self._entity.set_value(True)


class HCStartButton(HCEntity, ButtonEntity):
    """Start Button Entity."""

    _entity: ActiveProgram
    entity_description: HCButtonEntityDescription

    @property
    def available(self) -> bool:
        available = super().available
        available &= self._runtime_data.appliance.selected_program is not None
        if self._runtime_data.appliance.selected_program is not None:
            available &= (
                self._runtime_data.appliance.selected_program.execution
                == Execution.SELECT_AND_START
            )
        return available

    @error_decorator
    async def async_press(self) -> None:
        program = self._runtime_data.appliance.selected_program
        if program.full_option_set:
            # Some appliances validate a program write against the program's
            # complete option set and reject a partial one.
            await program.start(fill_full_option_set(program, {}), override_options=True)
        elif self._runtime_data.appliance.info.get("type") == COFFEE_MAKER_TYPE:
            # Coffee makers have been seen answering 400 to a start that carries
            # values for currently unavailable options; other appliance types keep
            # the plain start, so a 400 there stays a clean failure.
            await start_program_with_fallback(program)
        else:
            await program.start()
