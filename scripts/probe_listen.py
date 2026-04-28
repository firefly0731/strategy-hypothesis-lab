"""5-minute private WS listen test.

Subscribes to myOrder (5 major markets) + myAsset (account-wide).
Reports frame count by type and per-market breakdown for myOrder.
Tells us empirically whether the bot is currently active.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
import websockets

from observer.jwt_auth import make_bithumb_jwt

URL = "wss://ws-api.bithumb.com/websocket/v1/private"
MARKETS = ["KRW-USDT", "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
DURATION_SEC = 300


async def main() -> None:
    load_dotenv()
    api_key = os.environ.get("BITHUMB_API_KEY")
    api_secret = (
        os.environ.get("BITHUMB_API_SECRET")
        or os.environ.get("BITHUMB_SECRET_KEY")
    )
    if not api_key or not api_secret:
        sys.exit("API key/secret missing")

    token = make_bithumb_jwt(api_key=api_key, api_secret=api_secret)
    headers = [("Authorization", f"Bearer {token}")]

    sub = [
        {"ticket": "probe-listen"},
        {"type": "myOrder", "codes": MARKETS},
        {"type": "myAsset"},
        {"format": "DEFAULT"},
    ]

    counts = Counter()
    market_breakdown = Counter()
    first_seen: dict[str, float] = {}
    state_breakdown = Counter()  # for myOrder: state distribution

    started = time.monotonic()
    print(f"[probe] subscribed to myOrder({MARKETS}) + myAsset")
    print(f"[probe] listening {DURATION_SEC}s …\n")

    deadline = started + DURATION_SEC

    async with websockets.connect(URL, additional_headers=headers, ping_interval=30) as ws:
        await ws.send(json.dumps(sub))
        last_progress_t = started
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            txt = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            try:
                payload = json.loads(txt)
            except json.JSONDecodeError:
                continue
            if "error" in payload:
                print(f"[server ERROR] {payload}")
                continue
            mtype = payload.get("type", "?")
            counts[mtype] += 1
            if mtype not in first_seen:
                first_seen[mtype] = now - started
                print(f"  [t={now-started:5.1f}s] FIRST {mtype} arrived")
            if mtype == "myOrder":
                code = payload.get("code", "?")
                state = payload.get("state", "?")
                market_breakdown[code] += 1
                state_breakdown[state] += 1

            # progress heartbeat every 30s
            if now - last_progress_t >= 30:
                last_progress_t = now
                el = int(now - started)
                print(f"  [t={el:3d}s] counts so far: {dict(counts)}")

    el_total = time.monotonic() - started
    print()
    print("=" * 70)
    print(f"SUMMARY (after {el_total:.1f}s)")
    print("=" * 70)
    print(f"frame counts by type: {dict(counts)}")
    if counts.get("myOrder"):
        print(f"  myOrder by market:   {dict(market_breakdown)}")
        print(f"  myOrder by state:    {dict(state_breakdown)}")
    print(f"first-seen offsets:    {first_seen}")
    if not counts:
        print()
        print("⚠ Zero events in 5 minutes → bot is idle on all 5 major markets.")
    elif counts.get("myOrder", 0) > 0 and "KRW-USDT" not in market_breakdown:
        print()
        print(f"⚠ myOrder events arrived but NONE for KRW-USDT.")
        print(f"  → Bot trades {list(market_breakdown.keys())} but not KRW-USDT.")
    elif "KRW-USDT" in market_breakdown:
        n = market_breakdown["KRW-USDT"]
        print()
        print(f"✓ Bot IS active on KRW-USDT: {n} myOrder events captured.")


if __name__ == "__main__":
    asyncio.run(main())
