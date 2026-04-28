"""Observer entry point: runs all four channels concurrently for a fixed duration."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from observer.clock import Envelope
from observer.config import Config, load_config
from observer.writer import Writer
from observer.ws_private import run_private_ws_with_reconnect
from observer.ws_public import run_public_ws_with_reconnect

PUBLIC_URL = "wss://ws-api.bithumb.com/websocket/v1"
PRIVATE_URL = "wss://ws-api.bithumb.com/websocket/v1/private"
CHANNELS = ("orderbook", "trade", "myOrder", "myAsset")

_GLOBAL_STOP: asyncio.Event | None = None


def request_stop() -> None:
    """Trigger shutdown of the active run_capture (if any)."""
    if _GLOBAL_STOP is not None:
        _GLOBAL_STOP.set()


async def run_capture(
    *,
    cfg: Config,
    public_url: str = PUBLIC_URL,
    private_url: str = PRIVATE_URL,
) -> None:
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    started_utc_ms = int(time.time() * 1000)

    writers: dict[str, Writer] = {ch: Writer(channel=ch, run_dir=cfg.run_dir) for ch in CHANNELS}
    for w in writers.values():
        await w.start()

    counts: dict[str, int] = {ch: 0 for ch in CHANNELS}
    gaps: list[dict[str, Any]] = []

    async def on_event(channel: str, env: Envelope) -> None:
        if channel not in writers:
            return
        counts[channel] += 1
        await writers[channel].enqueue(env)

    stop_event = asyncio.Event()
    global _GLOBAL_STOP
    _GLOBAL_STOP = stop_event

    last_disconnect: dict[str, int] = {}

    def make_disconnect_cb(group: str):
        def cb() -> None:
            last_disconnect[group] = time.monotonic_ns()
        return cb

    def record_gap_if_pending(group: str) -> None:
        start = last_disconnect.pop(group, None)
        if start is None:
            return
        end = time.monotonic_ns()
        gaps.append(
            {
                "channel": group,
                "start_monotonic_ns": start,
                "end_monotonic_ns": end,
                "duration_ms": (end - start) // 1_000_000,
                "reason": "ws_disconnect",
            }
        )

    async def on_event_with_gap_close(channel: str, env: Envelope) -> None:
        # First event after a disconnect closes the gap for that group
        group = "private" if channel in ("myOrder", "myAsset") else "public"
        record_gap_if_pending(group)
        await on_event(channel, env)

    async def duration_timer() -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=cfg.duration_sec)
        except asyncio.TimeoutError:
            stop_event.set()

    public_task = asyncio.create_task(
        run_public_ws_with_reconnect(
            url=public_url, symbol=cfg.symbol,
            on_event=on_event_with_gap_close, stop_event=stop_event,
            on_disconnect=make_disconnect_cb("public"),
        )
    )
    private_task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=private_url, symbol=cfg.symbol, api_key=cfg.api_key, api_secret=cfg.api_secret,
            on_event=on_event_with_gap_close, stop_event=stop_event,
            on_disconnect=make_disconnect_cb("private"),
        )
    )
    timer_task = asyncio.create_task(duration_timer())

    try:
        await timer_task
    finally:
        stop_event.set()
        for t in (public_task, private_task):
            t.cancel()
        await asyncio.gather(public_task, private_task, return_exceptions=True)
        for w in writers.values():
            await w.close()
        _GLOBAL_STOP = None

    ended_utc_ms = int(time.time() * 1000)
    (cfg.run_dir / "meta.json").write_text(
        json.dumps(
            {
                "started_utc_ms": started_utc_ms,
                "ended_utc_ms": ended_utc_ms,
                "duration_planned_sec": cfg.duration_sec,
                "restart_count": 0,
                "gaps": gaps,
                "event_counts": counts,
                "symbol": cfg.symbol,
            },
            indent=2,
        )
    )


def main() -> None:
    import signal

    cfg = load_config()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop)
    try:
        loop.run_until_complete(run_capture(cfg=cfg))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
