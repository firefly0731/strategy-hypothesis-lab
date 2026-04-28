"""Bithumb Private WebSocket v2 client (myOrder + myAsset)."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import orjson
import websockets

from observer.backoff import ExponentialBackoff
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


async def run_private_ws_with_reconnect(
    *,
    url: str,
    api_key: str,
    api_secret: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
    backoff_start: float = 0.5,
    backoff_cap: float = 30.0,
    sustain_reset_sec: float = 60.0,
    max_reconnect_attempts: int | None = None,
    on_disconnect: Callable[[], None] | None = None,
) -> None:
    backoff = ExponentialBackoff(
        start=backoff_start, cap=backoff_cap, sustain_reset_sec=sustain_reset_sec
    )
    attempts = 0
    while not stop_event.is_set():
        try:
            backoff.mark_connected()
            await run_private_ws(
                url=url,
                api_key=api_key,
                api_secret=api_secret,
                on_event=on_event,
                stop_event=stop_event,
            )
        except PrivateAuthError:
            return  # immediate abort, never retry auth
        except (websockets.ConnectionClosed, OSError):
            pass
        if stop_event.is_set():
            return
        if on_disconnect is not None:
            on_disconnect()
        attempts += 1
        if max_reconnect_attempts is not None and attempts >= max_reconnect_attempts:
            return
        await asyncio.sleep(backoff.next_delay())
