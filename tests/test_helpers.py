"""Helper functions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from custom_components.homeconnect_ws.helpers import (
    EntityMatch,
    ensure_writable,
    error_decorator,
    get_entities_from_regex,
    get_groups_from_regex,
    is_locked_option,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DEVICE_DESCRIPTION

if TYPE_CHECKING:
    from homeconnect_websocket.testutils import MockApplianceType


async def test_get_entities_from_regex(mock_homeconnect_appliance: MockApplianceType) -> None:
    """Test get_entities_from_regex helper."""
    appliance = await mock_homeconnect_appliance(description=DEVICE_DESCRIPTION)
    pattern = re.compile(r"^Test\.RegEx\.(.*)\..*$")
    result = get_entities_from_regex(appliance, pattern)
    assert result == [
        EntityMatch(entity="Test.RegEx.001.Sensor", groups=("001",)),
        EntityMatch(entity="Test.RegEx.002.Sensor", groups=("002",)),
        EntityMatch(entity="Test.RegEx.001.Switch", groups=("001",)),
        EntityMatch(entity="Test.RegEx.002.Switch", groups=("002",)),
    ]


async def test_get_groups_from_regex(mock_homeconnect_appliance: MockApplianceType) -> None:
    """Test get_groups_from_regex helper."""
    appliance = await mock_homeconnect_appliance(description=DEVICE_DESCRIPTION)
    pattern = re.compile(r"^Test\.RegEx\.(.*)\..*$")
    result = get_groups_from_regex(appliance, pattern)
    assert result == {("001",), ("002",)}


async def test_error_decorator_timeout_becomes_homeassistant_error() -> None:
    """A bare asyncio TimeoutError from send_sync must not reach the frontend as-is."""

    @error_decorator
    async def raises_timeout() -> None:
        raise TimeoutError

    with pytest.raises(HomeAssistantError) as exc_info:
        await raises_timeout()

    assert exc_info.value.translation_key == "command_timeout"


async def test_is_locked_option(mock_homeconnect_appliance: MockApplianceType) -> None:
    """Only an Option with Access.READ counts as locked read-only."""
    appliance = await mock_homeconnect_appliance(description=DEVICE_DESCRIPTION)
    option = appliance.entities["Test.Option1"]
    setting = appliance.entities["Test.Switch"]

    await option.update({"access": "read"})
    assert is_locked_option(option) is True

    await option.update({"access": "readwrite"})
    assert is_locked_option(option) is False

    await option.update({"access": "none"})
    assert is_locked_option(option) is False

    await setting.update({"access": "read"})
    assert is_locked_option(setting) is False


async def test_ensure_writable(mock_homeconnect_appliance: MockApplianceType) -> None:
    """ensure_writable raises only for a locked Option."""
    appliance = await mock_homeconnect_appliance(description=DEVICE_DESCRIPTION)
    option = appliance.entities["Test.Option1"]

    await option.update({"access": "readwrite"})
    ensure_writable(option)

    await option.update({"access": "read"})
    with pytest.raises(ServiceValidationError):
        ensure_writable(option)
