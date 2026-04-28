"""Bithumb Private WebSocket v2 client (myOrder + myAsset)."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import orjson
import websockets

from observer.clock import stamp
from observer.jwt_auth import make_bithumb_jwt

OnEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


class PrivateAuthError(RuntimeError):
    pass


def _server_ts_ms_from_payload(payload: dict[str, Any]) -> int:
    content = payload.get("content") or {}
    ts = content.get("timestamp") if isinstance(content, dict) else None
    if isinstance(ts, str):
        try:
            return int(ts)
        except ValueError:
            return 0
    if isinstance(ts, int):
        return ts
    return 0


async def run_private_ws(
    *,
    url: str,
    api_key: str,
    api_secret: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
) -> None:
    token = make_bithumb_jwt(api_key=api_key, api_secret=api_secret)
    headers = [("Authorization", f"Bearer {token}")]
    try:
        async with websockets.connect(url, additional_headers=headers, ping_interval=30) as ws:
            sub = [
                {"ticket": "observer"},
                {"type": "myOrder"},
                {"type": "myAsset"},
                {"format": "DEFAULT"},
            ]
            await ws.send(orjson.dumps(sub).decode())  # send as text frame for mock_ws_server compat
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
    except websockets.InvalidStatusCode as e:
        if e.status_code in (401, 403):
            raise PrivateAuthError(f"Bithumb private auth rejected: {e.status_code}") from e
        raise
