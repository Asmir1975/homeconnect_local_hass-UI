"""Helper functions."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.service import async_extract_config_entry_ids
from homeconnect_websocket.entities import Access, Option, SelectedProgram
from homeconnect_websocket.errors import AccessError, CodeResponsError, NotConnectedError

from .const import DOMAIN

if TYPE_CHECKING:
    import re
    from collections.abc import Callable, Coroutine

    from homeassistant.core import HomeAssistant, ServiceCall
    from homeconnect_websocket import HomeAppliance
    from homeconnect_websocket.entities import DeviceDescription, Program
    from homeconnect_websocket.entities import Entity as HcEntity

    from . import HCConfigEntry, HCData
    from .entity import HCEntity

_LOGGER = logging.getLogger(__name__)

HTTP_BAD_REQUEST = 400
_START_RESOURCE = "/ro/activeProgram"


def create_entities(
    entities_classes: dict[str, type[HCEntity]], runtime_data: HCData
) -> set[HCEntity]:
    """Create entities from entity_descriptions."""
    entities = set()
    for entity_key, entity_class in entities_classes.items():
        if entity_key in runtime_data.available_entity_descriptions:
            for entity_description in runtime_data.available_entity_descriptions[entity_key]:
                _LOGGER.debug("Creating Entity %s", entity_description.key)
                try:
                    entity = entity_class(
                        entity_description=entity_description, runtime_data=runtime_data
                    )
                except Exception:
                    _LOGGER.exception("Failed to create Entity %s", entity_description.key)
                else:
                    entities.add(entity)
    return entities


def merge_dicts(*args: dict[str, list]) -> dict[str, list]:
    """Merge multiple dictionaries of type dict[str, list]."""
    out_dict: dict[str, list] = {}
    for in_dict in args:
        for key, value in in_dict.items():
            if key not in out_dict:
                out_dict[key] = value
            else:
                out_dict[key].extend(value)
    return out_dict


@dataclass
class EntityMatch:
    """Returned by get_entities_from_regex."""

    entity: str
    groups: tuple[str]


def get_entities_from_regex(appliance: HomeAppliance, pattern: re.Pattern) -> list[EntityMatch]:
    """Get all entities matching the pattern."""
    return [
        EntityMatch(entity=entity, groups=match.groups())
        for entity in appliance.entities
        if (match := pattern.match(entity))
    ]


def get_groups_from_regex(appliance: HomeAppliance, pattern: re.Pattern) -> set[tuple[str]]:
    """Get all regex groups matching the pattern."""
    groups = set()
    for entity in appliance.entities:
        if (match := pattern.match(entity)) and match.groups() not in groups:
            groups.add(match.groups())
    return groups


async def get_config_entry_from_call(
    hass: HomeAssistant, service_call: ServiceCall
) -> HCConfigEntry | None:
    """Get the config entry from a service call."""
    config_entry_ids = await async_extract_config_entry_ids(service_call)
    for config_entry_id in config_entry_ids:
        config_entry = hass.config_entries.async_get_entry(config_entry_id)
        if config_entry.domain == DOMAIN:
            return config_entry
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_appliance")


def entity_is_available(entity: HcEntity, available_access: tuple[Access]) -> bool:
    """Check is HC entity is available."""
    available = True
    if hasattr(entity, "available"):
        available &= entity.available

    if hasattr(entity, "access"):
        available &= entity.access in available_access
    return available


def is_option(entity: HcEntity | None) -> bool:
    """Whether entity is a program Option or SelectedProgram, regardless of its current access."""
    return isinstance(entity, Option | SelectedProgram)


def is_locked_option(entity: HcEntity | None) -> bool:
    """
    Whether entity is a program Option or SelectedProgram currently locked read-only.

    Home Connect locks some Options, and the program selector itself (e.g. during
    Delayed Start), to read-only while a program runs, rather than making them
    unapplicable; the official app shows these as visible-but-disabled, not hidden.
    Access.NONE ("not applicable at all") is unaffected and stays genuinely unavailable.
    """
    return isinstance(entity, Option | SelectedProgram) and entity.access == Access.READ


def ensure_writable(entity: HcEntity | None) -> None:
    """Raise a clear error instead of attempting a write a locked Option will reject."""
    if is_locked_option(entity):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="read_only",
        )


async def start_coffee_favorite_with_fallback(program: Program) -> None:
    """
    Start a coffee favorite, retrying once without unavailable options after a 400.

    The first attempt is the unchanged default start. Some coffee makers answer 400
    when the favorite's options include values for currently unavailable options
    (suspected cause on a Siemens TP713D09). Only such a 400 on the start resource is
    retried, once; any other error, timeout or disconnect is not, since the appliance
    might already have started.
    """
    try:
        await program.start()
    except CodeResponsError as exc:
        if exc.code != HTTP_BAD_REQUEST or exc.resource != _START_RESOURCE:
            raise
        writable = {
            option.uid: option.value_shadow
            for option in program.options
            if option.access == Access.READ_WRITE
        }
        reduced = {
            option.uid: option.value_shadow
            for option in program.options
            if option.access == Access.READ_WRITE
            and option.available is not False
            and option.value_shadow is not None
        }
        if reduced == writable:
            raise
        _LOGGER.debug("Start of %s answered 400, retrying with available options", program.name)
        await program.start(reduced, override_options=True)


def error_decorator[T](func: Callable[..., Coroutine[T]]) -> Callable[..., Coroutine[T]]:
    """Catches HomeConnect Errors and raise HomeAssistantError."""

    async def wrap(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except AccessError:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="access_error",
            ) from None
        except CodeResponsError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="code_respons",
                translation_placeholders={"message": exc.message},
            ) from None
        except NotConnectedError:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_connected",
            ) from None
        except TimeoutError:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_timeout",
            ) from None

    return wrap


def _invalid(message: str) -> Never:
    """Raise a user-facing validation error without any appliance write."""
    raise ValueError(message)


def _numeric_bound(definition: dict, key: str, name: str) -> float | None:
    """Decode numeric catalog metadata, which HA may persist as strings."""
    raw = definition.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        _invalid(f"Invalid catalog {key} for option: {name}")
    try:
        number = float(raw)
    except TypeError, ValueError:
        _invalid(f"Invalid catalog {key} for option: {name}")
    if not math.isfinite(number):
        _invalid(f"Invalid catalog {key} for option: {name}")
    return number


def _validate_value(
    name: str,
    value: str | float | bool,  # noqa: FBT001 - this is an option value, not a flag
    definition: dict,
    enumeration: dict | None,
) -> str | int | float | bool:
    """Validate and encode one explicit option value."""
    if enumeration:
        enum = {int(key): label for key, label in enumeration.items()}
        if isinstance(value, str) and value in enum.values():
            value = next(key for key, label in enum.items() if label == value)
        elif type(value) is not int or value not in enum:
            _invalid(f"Invalid enum value for option: {name}")
    else:
        types = {"Boolean": (bool,), "Integer": (int,), "String": (str,), "Float": (int, float)}
        kind = definition.get("protocolType")
        if kind in types and type(value) not in types[kind]:
            _invalid(f"Invalid {kind} value for option: {name}")
    if type(value) in (int, float):
        if not math.isfinite(value):
            _invalid(f"Finite number required for option: {name}")
        minimum = _numeric_bound(definition, "min", name)
        maximum = _numeric_bound(definition, "max", name)
        if minimum is not None and value < minimum:
            _invalid(f"Value below minimum for option: {name}")
        if maximum is not None and value > maximum:
            _invalid(f"Value above maximum for option: {name}")
        step = _numeric_bound(definition, "stepSize", name)
        if step is not None and step > 0:
            offset = (value - (minimum or 0)) / step
            if not math.isclose(offset, round(offset), abs_tol=1e-8):
                _invalid(f"Value does not match step for option: {name}")
    return value


def prepare_program_start(
    appliance: HomeAppliance,
    description: DeviceDescription,
    program_key: str,
    requested_options: dict[str, str | int | float | bool],
) -> tuple[Program, dict[int, str | int | float | bool]]:
    """
    Resolve names and validate values; never issue a preliminary write.

    Validate against the target program's description, not another selected
    program's context-dependent access flags. The appliance remains authoritative
    for additional dynamic constraints when receiving the single start request.
    """
    program = appliance.programs.get(program_key)
    if program is None or not program.available:
        _invalid(f"Program is unknown or unavailable: {program_key}")
    if program.execution not in ("startonly", "selectandstart"):
        _invalid(f"Program does not support start: {program_key}")

    program_description = next(
        (item for item in description.get("program", []) if item["uid"] == program.uid),
        None,
    )
    if program_description is None:
        _invalid("Target program description is missing")

    members = {item["refUID"]: item for item in program_description.get("options", [])}
    definitions = {item["uid"]: item for item in description.get("option", [])}
    result = {}
    for name, value in requested_options.items():
        option = appliance.options.get(name)
        member = members.get(option.uid) if option is not None else None
        if member is None:
            _invalid(f"Option does not belong to target program: {name}")
        definition = {**definitions.get(option.uid, {}), **member}
        if not definition.get("available", True) or definition.get("access") not in (
            "readwrite",
            "writeonly",
        ):
            _invalid(f"Option is not writable for target program: {name}")

        result[option.uid] = _validate_value(name, value, definition, option.enum)
    return program, result
