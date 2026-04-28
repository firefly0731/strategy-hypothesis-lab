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
