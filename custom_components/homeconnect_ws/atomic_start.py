"""Validate explicit program options without selecting or writing the appliance."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Never

if TYPE_CHECKING:
    from homeconnect_websocket import HomeAppliance
    from homeconnect_websocket.entities import DeviceDescription, Program


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
