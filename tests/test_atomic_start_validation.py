"""Validation/wire tests; no HA instance or appliance connection."""
# unittest makes this small validator suite runnable without HA's pytest fixtures.
# ruff: noqa: PT009, PT027

import asyncio
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.homeconnect_ws.helpers import prepare_program_start
from homeconnect_websocket.entities import Option, Program

PROGRAM = "Cooking.Oven.Program.HeatingMode.AirFry"
DURATION = "BSH.Common.Option.Duration"
TEMPERATURE = "Cooking.Oven.Option.SetpointTemperature"
CAVITY = "Cooking.Oven.Option.CavitySelector"


class AtomicStartTests(unittest.TestCase):
    """Test explicit options and the library's exact single-request path."""

    def setUp(self) -> None:
        self.description = {
            "option": [
                {
                    "uid": 548,
                    "name": DURATION,
                    "protocolType": "Integer",
                    "min": 1,
                    "max": 86400,
                    "access": "readwrite",
                    "default": 0,
                },
                {
                    "uid": 5120,
                    "name": TEMPERATURE,
                    "protocolType": "Integer",
                    "min": 30,
                    "max": 275,
                    "access": "readwrite",
                    "default": 160,
                },
                {
                    "uid": 5137,
                    "name": CAVITY,
                    "protocolType": "Integer",
                    "enumeration": {"1": "Main"},
                    "access": "readwrite",
                },
            ],
            "program": [
                {
                    "uid": 8277,
                    "name": PROGRAM,
                    "available": True,
                    "execution": "selectandstart",
                    "options": [
                        {"refUID": uid, "available": True, "access": "readwrite"}
                        for uid in (548, 5120, 5137)
                    ],
                }
            ],
        }
        self.appliance = SimpleNamespace(
            entities_uid={},
            options={},
            programs={},
            session=SimpleNamespace(send_sync=AsyncMock()),
        )
        for item in self.description["option"]:
            option = Option(item, self.appliance)
            self.appliance.options[option.name] = option
            self.appliance.entities_uid[option.uid] = option
        self.program = Program(self.description["program"][0], self.appliance)
        self.appliance.programs[PROGRAM] = self.program

    def prepare(self, options: dict) -> tuple:
        return prepare_program_start(self.appliance, self.description, PROGRAM, options)

    def test_explicit_values_replace_shadows_in_one_request(self) -> None:
        program, options = self.prepare({DURATION: 30, TEMPERATURE: 180, CAVITY: "Main"})
        asyncio.run(program.start(options, override_options=True))
        self.appliance.session.send_sync.assert_awaited_once()
        message = self.appliance.session.send_sync.call_args.args[0]
        self.assertEqual(message.resource, "/ro/activeProgram")
        self.assertEqual(message.action, "POST")
        self.assertEqual(
            message.data,
            {
                "program": 8277,
                "options": [
                    {"uid": 548, "value": 30},
                    {"uid": 5120, "value": 180},
                    {"uid": 5137, "value": 1},
                ],
            },
        )

    def test_no_unrequested_cached_options(self) -> None:
        program, options = self.prepare({DURATION: 30})
        asyncio.run(program.start(options, override_options=True))
        self.assertEqual(
            self.appliance.session.send_sync.call_args.args[0].data["options"],
            [{"uid": 548, "value": 30}],
        )

    def test_unknown_program(self) -> None:
        with self.assertRaises(ValueError):
            prepare_program_start(self.appliance, self.description, "unknown", {})

    def test_unavailable_program(self) -> None:
        self.program._available = False
        with self.assertRaises(ValueError):
            self.prepare({DURATION: 30})

    def test_foreign_option(self) -> None:
        with self.assertRaises(ValueError):
            self.prepare({"Cooking.Oven.Option.SteamAssistLevel": "High"})

    def test_read_only_program_option(self) -> None:
        self.description["program"][0]["options"][0]["access"] = "read"
        with self.assertRaises(ValueError):
            self.prepare({DURATION: 30})

    def test_target_bounds_override_global_bounds(self) -> None:
        self.description["program"][0]["options"][1]["max"] = 200
        with self.assertRaises(ValueError):
            self.prepare({TEMPERATURE: 210})

    def test_invalid_numeric_values(self) -> None:
        for value in (0, 86401, True, 30.5, "30", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.prepare({DURATION: value})

    def test_step_validation(self) -> None:
        self.description["option"][1]["stepSize"] = 5
        with self.assertRaises(ValueError):
            self.prepare({TEMPERATURE: 181})

    def test_string_catalog_bounds_and_step(self) -> None:
        self.description["option"][1].update(min="30", max="275", stepSize="5")
        self.assertEqual(self.prepare({TEMPERATURE: 180})[1], {5120: 180})
        for value in (25, 280, 181):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.prepare({TEMPERATURE: value})

    def test_string_target_bounds_override_global(self) -> None:
        self.description["program"][0]["options"][1]["max"] = "200"
        with self.assertRaises(ValueError):
            self.prepare({TEMPERATURE: 210})

    def test_invalid_catalog_bounds_fail_without_write(self) -> None:
        for value in ("invalid", "nan", "inf", True):
            with self.subTest(value=value):
                self.description["option"][1]["min"] = value
                with self.assertRaises(ValueError):
                    self.prepare({TEMPERATURE: 180})
                self.appliance.session.send_sync.assert_not_called()

    def test_enum_raw_value_and_invalid_labels(self) -> None:
        self.assertEqual(self.prepare({CAVITY: 1})[1], {5137: 1})
        for value in (True, 2, "Unknown", "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.prepare({CAVITY: value})

    def test_validation_does_not_write_or_change_shadows(self) -> None:
        before = deepcopy([o.value_shadow for o in self.appliance.options.values()])
        self.prepare({DURATION: 30, TEMPERATURE: 180})
        self.appliance.session.send_sync.assert_not_called()
        self.assertEqual(before, [o.value_shadow for o in self.appliance.options.values()])


if __name__ == "__main__":
    unittest.main()


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON keys rather than silently accepting the last value."""
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate translation key: {key}"
        result[key] = value
    return result


def test_start_program_with_options_translated() -> None:
    """The action and its fields are translated in en, de and it."""
    translations = Path(__file__).parents[1] / "custom_components/homeconnect_ws/translations"
    for language in ("en", "de", "it"):
        path = translations / f"{language}.json"
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
        service = data["services"]["start_program_with_options"]
        assert service["name"], path.name
        assert service["description"], path.name
        assert set(service["fields"]) == {"device_id", "program", "options"}, path.name
        for field in service["fields"].values():
            assert field["name"], path.name
            assert field["description"], path.name
