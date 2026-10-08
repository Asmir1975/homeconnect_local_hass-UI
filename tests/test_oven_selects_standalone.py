"""Offline mapping/enum checks, runnable without the Home Assistant test stack."""
# ruff: noqa: PT009, PT027

import ast
import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeconnect_websocket.entities import Option, Setting
from homeconnect_websocket.message import Action, Message

COMPONENT = Path(__file__).parents[1] / "custom_components/homeconnect_ws"
STEAM = "Cooking.Oven.Option.SteamAssistLevel"
HARDNESS = "Cooking.Oven.Setting.WaterHardness"


class OvenSelectTests(unittest.TestCase):
    """Check new descriptors and the pinned library's actual enum wire mapping."""

    def test_descriptors_use_device_enums(self) -> None:
        tree = ast.parse((COMPONENT / "entity_descriptions/cooking.py").read_text())
        calls = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "HCSelectEntityDescription":
                continue
            kwargs = {item.arg: item.value for item in node.keywords}
            key = kwargs.get("key")
            if isinstance(key, ast.Constant):
                calls[key.value] = kwargs
        for key, entity in (
            ("select_oven_steam_assist_level", STEAM),
            ("select_oven_water_hardness", HARDNESS),
        ):
            self.assertEqual(ast.literal_eval(calls[key]["entity"]), entity)
            self.assertTrue(ast.literal_eval(calls[key]["has_state_translation"]))
            self.assertNotIn("options", calls[key])
        self.assertNotIn("entity_category", calls["select_oven_steam_assist_level"])
        self.assertEqual(
            ast.unparse(calls["select_oven_water_hardness"]["entity_category"]),
            "EntityCategory.CONFIG",
        )

    def test_translation_states(self) -> None:
        for language in ("en", "it"):
            data = json.loads((COMPONENT / f"translations/{language}.json").read_text())
            selects = data["entity"]["select"]
            self.assertEqual(
                set(selects["select_oven_steam_assist_level"]["state"]),
                {"off", "low", "high"},
            )
            self.assertEqual(
                set(selects["select_oven_water_hardness"]["state"]),
                {"softened", "soft", "medium", "hard", "veryhard"},
            )

    def test_enum_values_sent_without_device_connection(self) -> None:
        appliance = SimpleNamespace(session=SimpleNamespace(send_sync=AsyncMock()))
        appliance.session.send_sync.return_value = Message(
            resource="/ro/values", action=Action.RESPONSE
        )
        for entity_class, name, uid, enumeration in (
            (Option, STEAM, 5125, {"0": "Off", "1": "Low", "3": "High"}),
            (
                Setting,
                HARDNESS,
                4367,
                {"0": "Softened", "1": "Soft", "2": "Medium", "3": "Hard", "4": "VeryHard"},
            ),
        ):
            entity = entity_class(
                {
                    "uid": uid,
                    "name": name,
                    "protocolType": "Integer",
                    "access": "readwrite",
                    "available": True,
                    "enumeration": enumeration,
                },
                appliance,
            )
            for raw, label in enumeration.items():
                appliance.session.send_sync.reset_mock()
                asyncio.run(entity.set_value(label))
                appliance.session.send_sync.assert_awaited_once_with(
                    Message(
                        resource="/ro/values",
                        action=Action.POST,
                        data={"uid": uid, "value": int(raw)},
                    )
                )
            appliance.session.send_sync.reset_mock()
            with self.assertRaises(ValueError):
                asyncio.run(entity.set_value("Level2" if name == STEAM else "Unknown"))
            appliance.session.send_sync.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
