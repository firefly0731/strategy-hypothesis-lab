"""One-off diagnostic: connect to live Bithumb v2 WebSockets, dump a few frames per channel.

Purpose: verify actual field names in `myOrder`/`myAsset` payloads (and confirm public
channel structure) so we can correctly patch `observer.convert` flatteners.

Usage:
    python scripts/probe_live.py [--duration-sec 60] [--max-per-channel 3]

Reads BITHUMB_API_KEY / BITHUMB_API_SECRET / OBSERVER_SYMBOL from `.env`.

This is a passive observer:
- Read-only API key only (per .env).
- Single connection per WS endpoint, no polling, no order placement.
- Stops automatically after duration_sec or when max-per-channel frames captured per channel.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Make src/observer importable.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from observer.ws_private import run_private_ws  # noqa: E402
from observer.ws_public import run_public_ws  # noqa: E402


def _summarize_keys(payload: dict) -> dict:
    """Return a tree of keys (no values) so we can see field structure without exposing PII."""
    if isinstance(payload, dict):
        return {k: _summarize_keys(v) for k, v in payload.items()}
    if isinstance(payload, list):
        if payload and isinstance(payload[0], (dict, list)):
            return [_summarize_keys(payload[0]), f"... ({len(payload)} items)"]
        return f"<list len={len(payload)}>"
    return type(payload).__name__


def _redact_for_print(payload, *, is_private: bool):
    """For private events: collapse values to type names so we see structure but no PII.
    For public events (no PII): pass through unchanged."""
    if not is_private:
        return payload
    if isinstance(payload, dict):
        return {k: _redact_for_print(v, is_private=True) for k, v in payload.items()}
    if isinstance(payload, list):
        if not payload:
            return []
        # Show only the first element (collapsed) and a count
        return [_redact_for_print(payload[0], is_private=True), f"... (list len={len(payload)})"]
    # Leaf: replace value with its type name
    return f"<{type(payload).__name__}>"


async def main(duration_sec: int, max_per_channel: int) -> None:
    load_dotenv()

    api_key = os.environ.get("BITHUMB_API_KEY")
    # Accept either name; user's .env may use Bithumb's BITHUMB_SECRET_KEY convention.
    api_secret = (
        os.environ.get("BITHUMB_API_SECRET")
        or os.environ.get("BITHUMB_SECRET_KEY")
    )
    symbol = os.environ.get("OBSERVER_SYMBOL", "KRW-XRP")
    if not api_key or not api_secret:
        sys.exit("BITHUMB_API_KEY / (BITHUMB_API_SECRET | BITHUMB_SECRET_KEY) missing from .env")

    counts: dict[str, int] = defaultdict(int)
    seen_keys: dict[str, set[str]] = defaultdict(set)
    samples: dict[str, list] = defaultdict(list)

    stop_event = asyncio.Event()

    async def on_event_public(channel: str, env: dict) -> None:
        if counts[channel] >= max_per_channel:
            return
        counts[channel] += 1
        raw = env["raw"]
        content = raw.get("content") or {}
        seen_keys[channel].update(content.keys() if isinstance(content, dict) else [])
        samples[channel].append(_redact_for_print(raw, is_private=False))
        if all(counts[c] >= max_per_channel for c in ("orderbookdepth", "transaction")):
            # Public side done early
            pass

    async def on_event_private(channel: str, env: dict) -> None:
        if counts[channel] >= max_per_channel:
            return
        counts[channel] += 1
        raw = env["raw"]
        content = raw.get("content") or {}
        seen_keys[channel].update(content.keys() if isinstance(content, dict) else [])
        samples[channel].append(_redact_for_print(raw, is_private=True))

    print(f"[probe] connecting to live Bithumb (symbol={symbol}, duration={duration_sec}s)…")
    print(f"[probe] capturing up to {max_per_channel} frames per channel.")
    print()

    pub_url = "wss://ws-api.bithumb.com/websocket/v1"
    priv_url = "wss://ws-api.bithumb.com/websocket/v1/private"

    public_task = asyncio.create_task(
        run_public_ws(url=pub_url, symbol=symbol, on_event=on_event_public, stop_event=stop_event)
    )
    private_task = asyncio.create_task(
        run_private_ws(
            url=priv_url, api_key=api_key, api_secret=api_secret,
            symbol=symbol,
            on_event=on_event_private, stop_event=stop_event,
        )
    )
    timer = asyncio.create_task(asyncio.sleep(duration_sec))

    done, pending = await asyncio.wait(
        [public_task, private_task, timer], return_when=asyncio.FIRST_COMPLETED
    )
    stop_event.set()
    for t in (public_task, private_task, timer):
        t.cancel()
    for t in (public_task, private_task, timer):
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    print("=" * 70)
    print("PROBE SUMMARY")
    print("=" * 70)

    for ch in ("orderbook", "trade", "myOrder", "myAsset"):
        n = counts.get(ch, 0)
        keys = sorted(seen_keys.get(ch, set()))
        print(f"\n--- {ch}: captured {n} frames ---")
        if n == 0:
            print("  (no frames received)")
            continue
        print(f"  content.* keys observed: {keys}")
        print("  first sample (with PII redacted for private):")
        sample = samples[ch][0]
        print(json.dumps(sample, indent=2, ensure_ascii=False, default=str))

    print()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-sec", type=int, default=60)
    parser.add_argument("--max-per-channel", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(main(args.duration_sec, args.max_per_channel))
