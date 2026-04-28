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

PUBLIC_URL = "wss://pubwss.bithumb.com/pub/ws"
PRIVATE_URL = "wss://ws-api.bithumb.com/websocket/v1/private"
CHANNELS = ("orderbookdepth", "transaction", "myOrder", "myAsset")


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

    async def on_event(channel: str, env: Envelope) -> None:
        if channel not in writers:
            return
        counts[channel] += 1
        await writers[channel].enqueue(env)

    stop_event = asyncio.Event()

    async def duration_timer() -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=cfg.duration_sec)
        except asyncio.TimeoutError:
            stop_event.set()

    public_task = asyncio.create_task(
        run_public_ws_with_reconnect(
            url=public_url,
            symbol=cfg.symbol,
            on_event=on_event,
            stop_event=stop_event,
        )
    )
    private_task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=private_url,
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
            on_event=on_event,
            stop_event=stop_event,
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

    ended_utc_ms = int(time.time() * 1000)
    (cfg.run_dir / "meta.json").write_text(
        json.dumps(
            {
                "started_utc_ms": started_utc_ms,
                "ended_utc_ms": ended_utc_ms,
                "duration_planned_sec": cfg.duration_sec,
                "restart_count": 0,
                "gaps": [],
                "event_counts": counts,
                "symbol": cfg.symbol,
            },
            indent=2,
        )
    )


def main() -> None:
    cfg = load_config()
    asyncio.run(run_capture(cfg=cfg))


if __name__ == "__main__":
    main()
