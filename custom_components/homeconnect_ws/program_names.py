"""Favorite program labels taken from the current appliance state."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeconnect_websocket import HomeAppliance
    from homeconnect_websocket.entities import Setting

FAVORITE_PREFIX = "BSH.Common.Program.Favorite."
_NAME_SETTING = "BSH.Common.Setting.Favorite.{slot}.Name"
_FUNCTIONALITY_SETTING = "BSH.Common.Setting.Favorite.{slot}.Functionality"
_SAVED_FUNCTIONALITY = "Program"


def favorite_name_settings(
    appliance: HomeAppliance, mapping: Mapping[str, str], *, with_functionality: bool = False
) -> list[Setting]:
    """Return the settings of all favorite slots, to be observed by an entity."""
    templates = [_NAME_SETTING]
    if with_functionality:
        templates.append(_FUNCTIONALITY_SETTING)
    settings = []
    for program in mapping:
        if program.startswith(FAVORITE_PREFIX):
            slot = program[len(FAVORITE_PREFIX) :]
            for template in templates:
                setting = appliance.settings.get(template.format(slot=slot))
                if setting is not None:
                    settings.append(setting)
    return settings


def program_labels(appliance: HomeAppliance, mapping: Mapping[str, str]) -> dict[str, str]:
    """
    Return one unique label per program.

    The appliance sends the favorite names after the entities are created, so the
    labels are read from the settings each time instead of being fixed at setup.
    Two favorites with the same name get their slot appended, because the label is
    what maps a selection back to a program.
    """
    labels = dict(mapping)
    for program in labels:
        if program.startswith(FAVORITE_PREFIX):
            slot = program[len(FAVORITE_PREFIX) :]
            setting = appliance.settings.get(_NAME_SETTING.format(slot=slot))
            value = setting.value if setting is not None else None
            labels[program] = (
                value.strip() if isinstance(value, str) and value.strip() else f"favorite_{slot}"
            )
    counts = Counter(labels.values())
    reserved = set(labels.values())
    for program, label in list(labels.items()):
        if program.startswith(FAVORITE_PREFIX) and counts[label] > 1:
            suffix = f" ({program[len(FAVORITE_PREFIX) :]})"
            candidate = label + suffix
            while candidate in reserved:
                candidate += suffix
            labels[program] = candidate
            reserved.add(candidate)
    return labels


def selectable_program_labels(
    appliance: HomeAppliance, mapping: Mapping[str, str]
) -> dict[str, str]:
    """
    Return the labels without favorite slots the user has not saved.

    A slot counts as saved when the appliance reports its functionality as
    "Program". Appliances that do not report the flag keep a slot if it has a name.
    Ordinary programs are never removed.
    """
    labels = program_labels(appliance, mapping)
    for program in list(labels):
        if not program.startswith(FAVORITE_PREFIX):
            continue
        slot = program[len(FAVORITE_PREFIX) :]
        functionality = appliance.settings.get(_FUNCTIONALITY_SETTING.format(slot=slot))
        if functionality is not None and functionality.value is not None:
            saved = functionality.value == _SAVED_FUNCTIONALITY
        else:
            name = appliance.settings.get(_NAME_SETTING.format(slot=slot))
            saved = name is not None and isinstance(name.value, str) and bool(name.value.strip())
        if not saved:
            del labels[program]
    return labels
