import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from observer.ws_public import run_public_ws

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
