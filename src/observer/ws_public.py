"""Bithumb public WebSocket v2 client (Upbit-compatible protocol).

Subscribes to `orderbook` and `trade` channels for one symbol and dispatches
every incoming frame to a user-supplied callback wrapped in an Envelope.
Reconnect with backoff is layered on top in run_public_ws_with_reconnect.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import orjson
import websockets

from observer.backoff import ExponentialBackoff
from observer.clock import stamp

OnEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


def _server_ts_ms_from_payload(payload: dict[str, Any]) -> int:
    """Extract server timestamp from top-level `timestamp` field (ms-since-epoch int)."""
    ts = payload.get("timestamp")
    if isinstance(ts, int):
        return ts
    if isinstance(ts, str):
        try:
            return int(ts)
        except ValueError:
            return 0
    return 0


async def run_public_ws(
    *,
    url: str,
    symbol: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
) -> None:
    """Single-attempt WS run. Returns when stop_event is set or connection closes."""
    async with websockets.connect(url, ping_interval=30) as ws:
        sub = [
            {"ticket": "observer-public"},
            {"type": "orderbook", "codes": [symbol]},
            {"type": "trade", "codes": [symbol]},
            {"format": "DEFAULT"},
        ]
        await ws.send(orjson.dumps(sub).decode())
        async for raw_msg in ws:
            if stop_event.is_set():
                return
            payload = orjson.loads(raw_msg)
            channel = payload.get("type", "unknown")
            env = stamp(
                channel=channel,
                server_ts_ms=_server_ts_ms_from_payload(payload),
                raw=payload,
            )
            await on_event(channel, env)


async def run_public_ws_with_reconnect(
    *,
    url: str,
    symbol: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
    backoff_start: float = 0.5,
    backoff_cap: float = 30.0,
    sustain_reset_sec: float = 60.0,
    on_disconnect: Callable[[], None] | None = None,
) -> None:
    """Outer loop: connect → run → on disconnect, backoff and reconnect."""
    backoff = ExponentialBackoff(
        start=backoff_start, cap=backoff_cap, sustain_reset_sec=sustain_reset_sec
    )
    while not stop_event.is_set():
        try:
            backoff.mark_connected()
            await run_public_ws(url=url, symbol=symbol, on_event=on_event, stop_event=stop_event)
        except (websockets.ConnectionClosed, OSError):
            pass
        if stop_event.is_set():
            return
        if on_disconnect is not None:
            on_disconnect()
        await asyncio.sleep(backoff.next_delay())
