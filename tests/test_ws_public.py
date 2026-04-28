import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from observer.ws_public import run_public_ws, run_public_ws_with_reconnect

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_public_ws_subscribes_and_dispatches(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample_orderbook = json.loads((FIXTURES / "orderbookdepth_sample.json").read_text())
    sample_trade = json.loads((FIXTURES / "transaction_sample.json").read_text())
    server.controller.pushes = [sample_orderbook, sample_trade]

    received: list[tuple[str, dict]] = []
    stop_event = asyncio.Event()

    async def on_event(channel: str, env: dict) -> None:
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    task = asyncio.create_task(
        run_public_ws(
            url=f"ws://localhost:{port}",
            symbol="USDT_KRW",
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

    # Subscriptions sent
    sub_types = {msg["type"] for msg in server.controller.received}
    assert sub_types == {"orderbookdepth", "transaction"}

    # Both events delivered with envelope shape
    channels = [c for c, _ in received]
    assert "orderbookdepth" in channels and "transaction" in channels
    for _, env in received:
        assert {"channel", "server_ts_ms", "recv_monotonic_ns", "recv_utc_ms", "raw"} <= set(env.keys())


@pytest.mark.asyncio
async def test_public_ws_reconnects_after_disconnect(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample = json.loads((FIXTURES / "transaction_sample.json").read_text())

    # First connection: send 1 frame then drop.
    server.controller.pushes = [sample]
    server.controller.drop_after = 0  # close immediately after pushes

    received: list[tuple[str, dict]] = []
    stop_event = asyncio.Event()

    async def on_event(channel, env):
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    task = asyncio.create_task(
        run_public_ws_with_reconnect(
            url=f"ws://localhost:{port}",
            symbol="USDT_KRW",
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
    # The mock server's controller is shared across reconnects, so received contains
    # subscribe frames from at least 2 connection attempts.
    sub_count = sum(1 for m in server.controller.received if m.get("type") == "transaction")
    assert sub_count >= 2
