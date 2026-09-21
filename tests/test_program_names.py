"""Tests for favorite program labels."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from custom_components.homeconnect_ws.program_names import program_labels

FAV1 = "BSH.Common.Program.Favorite.001"
FAV2 = "BSH.Common.Program.Favorite.002"


def _appliance(**names: object) -> Mock:
    appliance = Mock()
    appliance.settings = {
        f"BSH.Common.Setting.Favorite.{slot}.Name": SimpleNamespace(value=value)
        for slot, value in names.items()
    }
    return appliance


@pytest.mark.parametrize("value", [None, "", "  ", 123, {}])
def test_missing_or_invalid_name_falls_back_to_slot(value: object) -> None:
    """A missing or unusable name keeps the slot label."""
    assert program_labels(_appliance(**{"001": value}), {FAV1: "favorite_001"}) == {
        FAV1: "favorite_001"
    }


def test_name_is_taken_from_current_setting() -> None:
    """The current setting value wins over the label given at setup."""
    assert program_labels(_appliance(**{"001": " Pizza "}), {FAV1: "favorite_001"}) == {
        FAV1: "Pizza"
    }


def test_duplicate_names_get_their_slot() -> None:
    """Equal favorite names are made unique, other programs stay untouched."""
    labels = program_labels(
        _appliance(**{"001": "coffee", "002": "coffee"}),
        {FAV1: "x", FAV2: "y", "Coffee": "coffee", "Other": "coffee (001)"},
    )
    assert len(set(labels.values())) == len(labels)
    assert labels["Coffee"] == "coffee"
    assert labels["Other"] == "coffee (001)"
    assert labels[FAV1] != "coffee"
    assert labels[FAV2] != "coffee"
