"""Bithumb public WebSocket client.

Subscribes to `orderbookdepth` and `transaction` channels for one symbol and
dispatches every incoming frame to a user-supplied callback wrapped in an
Envelope. Reconnect with backoff is layered on top in run_public_ws_with_reconnect.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import orjson
import websockets

from observer.clock import stamp

OnEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


def _server_ts_ms_from_payload(payload: dict[str, Any]) -> int:
    """Best-effort extract of server timestamp.

    `orderbookdepth` puts it at content.datetime (string ms).
    `transaction` puts it at content.list[*].contDtm (string KST).
    Falls back to 0 if absent — analysis still has recv_monotonic_ns.
    """
    content = payload.get("content") or {}
    if isinstance(content.get("datetime"), str):
        try:
            return int(content["datetime"])
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
        await ws.send(orjson.dumps({"type": "orderbookdepth", "symbols": [symbol]}).decode())
        await ws.send(orjson.dumps({"type": "transaction", "symbols": [symbol]}).decode())
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
