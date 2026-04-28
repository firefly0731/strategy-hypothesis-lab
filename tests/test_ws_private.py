import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from observer.ws_private import run_private_ws

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_private_ws_subscribes_and_dispatches(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample_order = json.loads((FIXTURES / "myorder_sample.json").read_text())
    sample_asset = json.loads((FIXTURES / "myasset_sample.json").read_text())
    server.controller.pushes = [sample_order, sample_asset]

    received: list[tuple[str, dict]] = []
    stop_event = asyncio.Event()

    async def on_event(channel: str, env: dict) -> None:
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    task = asyncio.create_task(
        run_private_ws(
            url=f"ws://localhost:{port}",
            api_key="ak",
            api_secret="sk",
            on_event=on_event,
            stop_event=stop_event,
        )
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    channels = [c for c, _ in received]
    assert "myOrder" in channels
    assert "myAsset" in channels

    # Subscription frame must include both channel types
    sub_types = set()
    for msg in server.controller.received:
        if isinstance(msg, list):
            for entry in msg:
                if isinstance(entry, dict) and "type" in entry:
                    sub_types.add(entry["type"])
    assert {"myOrder", "myAsset"} <= sub_types


@pytest.mark.asyncio
async def test_private_ws_reconnects_on_drop(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample = json.loads((FIXTURES / "myasset_sample.json").read_text())
    server.controller.pushes = [sample]
    server.controller.drop_after = 1  # close after 1 received frame (the sub array)

    received: list[tuple[str, dict]] = []
    stop_event = asyncio.Event()

    async def on_event(channel, env):
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    from observer.ws_private import run_private_ws_with_reconnect
    task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=f"ws://localhost:{port}",
            api_key="ak",
            api_secret="sk",
            on_event=on_event,
            stop_event=stop_event,
            backoff_start=0.05,
            backoff_cap=0.2,
        )
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=3.0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(received) >= 2


@pytest.mark.asyncio
async def test_private_ws_aborts_on_auth_failure(mock_ws_server) -> None:
    server, port = mock_ws_server
    server.controller.reject_with_code = 4001  # any non-1000 close code

    received: list = []
    stop_event = asyncio.Event()

    async def on_event(channel, env):
        received.append((channel, env))

    from observer.ws_private import run_private_ws_with_reconnect
    task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=f"ws://localhost:{port}",
            api_key="ak",
            api_secret="sk",
            on_event=on_event,
            stop_event=stop_event,
            backoff_start=0.05,
            backoff_cap=0.1,
            max_reconnect_attempts=3,
        )
    )
    # Should complete on its own (give up after attempts) within a small window.
    await asyncio.wait_for(task, timeout=2.0)
    # No events were ever pushed, but we want to verify the function returned cleanly.
    assert received == []
