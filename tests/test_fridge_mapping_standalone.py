"""Offline refrigerator descriptor, translation and boolean wire checks."""
# ruff: noqa: PT009

import ast
import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeconnect_websocket.entities import Setting
from homeconnect_websocket.message import Action, Message

COMPONENT = Path(__file__).parents[1] / "custom_components/homeconnect_ws"
KEY = "switch_freezer_auto_super"
NAME = "Refrigeration.Common.Setting.Appliance.AutoSuper"


class FridgeMappingTests(unittest.TestCase):
    """Tests never connect to an appliance."""

    def test_descriptor(self) -> None:
        tree = ast.parse((COMPONENT / "entity_descriptions/refrigeration.py").read_text())
        matching = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "HCSwitchEntityDescription":
                continue
            kwargs = {item.arg: item.value for item in node.keywords}
            key = kwargs.get("key")
            if isinstance(key, ast.Constant) and key.value == KEY:
                matching.append(kwargs)
        self.assertEqual(len(matching), 1)
        self.assertEqual(ast.literal_eval(matching[0]["entity"]), NAME)
        self.assertEqual(ast.unparse(matching[0]["entity_category"]), "EntityCategory.CONFIG")
        self.assertEqual(ast.unparse(matching[0]["device_class"]), "SwitchDeviceClass.SWITCH")

    def test_translations_and_existing_identifiers(self) -> None:
        for language in ("en", "it"):
            data = json.loads((COMPONENT / f"translations/{language}.json").read_text())
            self.assertTrue(data["entity"]["switch"][KEY]["name"])
            self.assertTrue(
                data["entity"]["switch"]["switch_refrigeration_light_theater_mode"]["name"]
            )
            self.assertTrue(data["entity"]["light"]["light_internal"]["name"])

    def test_boolean_writes(self) -> None:
        send = AsyncMock(return_value=Message(resource="/ro/values", action=Action.RESPONSE))
        appliance = SimpleNamespace(session=SimpleNamespace(send_sync=send))
        setting = Setting(
            {
                "uid": 8249,
                "name": NAME,
                "protocolType": "Boolean",
                "access": "readwrite",
                "available": True,
            },
            appliance,
        )
        for value in (False, True):
            send.reset_mock()
            asyncio.run(setting.set_value(value))
            send.assert_awaited_once_with(
                Message(
                    resource="/ro/values", action=Action.POST, data={"uid": 8249, "value": value}
                )
            )


if __name__ == "__main__":
    unittest.main()
