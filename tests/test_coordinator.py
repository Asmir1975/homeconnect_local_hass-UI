"""Tests for the coordinator initial connect loop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.homeconnect_ws import coordinator
from custom_components.homeconnect_ws.const import (
    INITIAL_CONNECT_BACKOFF,
    MAX_CONNECT_BACKOFF,
)
from homeassistant.const import CONF_DESCRIPTION, CONF_HOST
from homeconnect_websocket import ConnectionFailedError


def _make_coordinator(connect: object) -> coordinator.HomeConnectCoordinator:
    """Build a bare coordinator with just what _connect() touches."""
    coord = object.__new__(coordinator.HomeConnectCoordinator)
    coord._connecting = True
    coord.connected = False
    coord.logger = MagicMock()
    coord.async_set_updated_data = MagicMock()
    coord.config_entry = SimpleNamespace(
        data={CONF_HOST: "10.0.0.9", CONF_DESCRIPTION: {"info": {"vib": "TEST"}}}
    )
    coord.appliance = SimpleNamespace(
        connect=connect,
        close=AsyncMock(),
        session=SimpleNamespace(connected=False),
    )
    return coord


async def test_connect_backs_off_on_repeated_failure() -> None:
    """A permanently failing connect waits between attempts with a growing delay."""
    attempts = 0

    async def fail() -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 4:
            coord._connecting = False
        raise ConnectionFailedError

    coord = _make_coordinator(fail)
    with patch.object(coordinator.asyncio, "sleep", new=AsyncMock()) as sleep:
        await coord._connect()

    assert attempts == 4
    assert sleep.await_count == 3
    delays = [call.args[0] for call in sleep.await_args_list]
    assert delays == [
        INITIAL_CONNECT_BACKOFF,
        INITIAL_CONNECT_BACKOFF * 2,
        INITIAL_CONNECT_BACKOFF * 4,
    ]


async def test_connect_backs_off_when_returned_without_connection() -> None:
    """connect() returning without raising but not connected also backs off."""
    attempts = 0

    async def returns_not_connected() -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 3:
            coord._connecting = False

    coord = _make_coordinator(returns_not_connected)
    with patch.object(coordinator.asyncio, "sleep", new=AsyncMock()) as sleep:
        await coord._connect()

    assert attempts == 3
    assert sleep.await_count == 2


async def test_connect_backs_off_on_unexpected_error() -> None:
    """An unexpected exception keeps retrying, but with the same backoff."""
    attempts = 0

    async def boom() -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 3:
            coord._connecting = False
        raise RuntimeError

    coord = _make_coordinator(boom)
    with patch.object(coordinator.asyncio, "sleep", new=AsyncMock()) as sleep:
        await coord._connect()

    assert attempts == 3
    assert sleep.await_count == 2


async def test_connect_succeeds_after_failures() -> None:
    """After transient failures the connect succeeds once and stops."""
    attempts = 0

    async def fail_then_ok() -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise ConnectionFailedError
        coord.appliance.session.connected = True

    coord = _make_coordinator(fail_then_ok)
    with patch.object(coordinator.asyncio, "sleep", new=AsyncMock()) as sleep:
        await coord._connect()

    assert attempts == 3
    assert coord.connected is True
    assert sleep.await_count == 2
    coord.async_set_updated_data.assert_called_once_with(None)


async def test_connect_stops_when_closed_during_backoff() -> None:
    """close() during the wait ends the loop without another attempt."""
    attempts = 0

    async def always_fail() -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionFailedError

    coord = _make_coordinator(always_fail)

    async def stop_during_sleep(_delay: float) -> None:
        coord._connecting = False

    with patch.object(coordinator.asyncio, "sleep", new=AsyncMock(side_effect=stop_during_sleep)):
        await coord._connect()

    assert attempts == 1


async def test_connect_backoff_is_capped() -> None:
    """The delay stops growing at MAX_CONNECT_BACKOFF."""
    attempts = 0

    async def always_fail() -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 12:
            coord._connecting = False
        raise ConnectionFailedError

    coord = _make_coordinator(always_fail)
    with patch.object(coordinator.asyncio, "sleep", new=AsyncMock()) as sleep:
        await coord._connect()

    delays = [call.args[0] for call in sleep.await_args_list]
    assert delays[-1] == MAX_CONNECT_BACKOFF
    assert all(delay <= MAX_CONNECT_BACKOFF for delay in delays)


def _make_reconnect_coordinator() -> coordinator.HomeConnectCoordinator:
    """Build a bare coordinator with just what _connection_state_callback() touches."""
    coord = object.__new__(coordinator.HomeConnectCoordinator)
    coord._connecting = True
    coord._reconnecting = False
    coord._reconnect_timer = None
    coord.connected = False
    coord.logger = MagicMock()
    coord.async_set_updated_data = MagicMock()
    coord.config_entry = SimpleNamespace(data={CONF_DESCRIPTION: {"info": {"vib": "TEST"}}})
    coord.appliance = SimpleNamespace(close=AsyncMock(), session=SimpleNamespace(connected=False))
    coord.hass = MagicMock()
    coord.hass.loop.time.return_value = 0.0
    return coord


async def test_reconnect_timer_is_cancelled_on_reconnect() -> None:
    """A successful reconnect must cancel its own grace-period timer."""
    coord = _make_reconnect_coordinator()
    handle = MagicMock(name="TimerHandle")
    coord.hass.loop.call_at.return_value = handle

    await coord._connection_state_callback(coordinator.ConnectionState.RECONNECTING)
    assert coord._reconnect_timer is handle

    await coord._connection_state_callback(coordinator.ConnectionState.CONNECTED)

    handle.cancel.assert_called_once()
    assert coord._reconnect_timer is None


async def test_reconnect_timer_is_cancelled_on_closed() -> None:
    """A final disconnect (CLOSED) must also cancel a pending grace-period timer."""
    coord = _make_reconnect_coordinator()
    handle = MagicMock(name="TimerHandle")
    coord.hass.loop.call_at.return_value = handle

    await coord._connection_state_callback(coordinator.ConnectionState.RECONNECTING)
    await coord._connection_state_callback(coordinator.ConnectionState.CLOSED)

    handle.cancel.assert_called_once()
    assert coord._reconnect_timer is None


async def test_close_cancels_pending_reconnect_timer() -> None:
    """close() must not leave a reconnect grace-period timer pending."""
    coord = _make_reconnect_coordinator()
    handle = MagicMock(name="TimerHandle")
    coord.hass.loop.call_at.return_value = handle

    await coord._connection_state_callback(coordinator.ConnectionState.RECONNECTING)
    await coord.close()

    handle.cancel.assert_called_once()
    assert coord._reconnect_timer is None


async def test_second_reconnect_cycle_gets_its_own_timer() -> None:
    """After a cycle completes cleanly, a later disconnect gets a fresh timer."""
    coord = _make_reconnect_coordinator()
    handle_a = MagicMock(name="TimerHandleA")
    coord.hass.loop.call_at.return_value = handle_a
    await coord._connection_state_callback(coordinator.ConnectionState.RECONNECTING)
    await coord._connection_state_callback(coordinator.ConnectionState.CONNECTED)

    handle_b = MagicMock(name="TimerHandleB")
    coord.hass.loop.call_at.return_value = handle_b
    await coord._connection_state_callback(coordinator.ConnectionState.RECONNECTING)

    assert coord._reconnect_timer is handle_b
    handle_a.cancel.assert_called_once()
