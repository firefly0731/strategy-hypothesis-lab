"""Raw diagnostic probe: try multiple subscribe formats against Bithumb v2 WS.

Goal: figure out exactly which subscribe payload makes data flow.
Tries 3 candidates against the public endpoint, prints what comes back.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import websockets

URL = "wss://ws-api.bithumb.com/websocket/v1"
SYMBOL = "KRW-XRP"


CANDIDATES = [
    (
        "v2 array format with orderbookdepth+transaction (Upbit-style)",
        [
            {"ticket": "probe-1"},
            {"type": "orderbookdepth", "codes": [SYMBOL]},
            {"type": "transaction", "codes": [SYMBOL]},
            {"format": "DEFAULT"},
        ],
    ),
    (
        "v2 array format with orderbook+trade (alternate names)",
        [
            {"ticket": "probe-2"},
            {"type": "orderbook", "codes": [SYMBOL]},
            {"type": "trade", "codes": [SYMBOL]},
            {"format": "DEFAULT"},
        ],
    ),
    (
        "v2 array format with ticker only (sanity check)",
        [
            {"ticket": "probe-3"},
            {"type": "ticker", "codes": [SYMBOL]},
            {"format": "DEFAULT"},
        ],
    ),
]


async def try_one(label: str, sub_payload: list, listen_sec: int = 8) -> None:
    print(f"\n{'='*70}")
    print(f"TRYING: {label}")
    print(f"  subscribe: {json.dumps(sub_payload)}")
    print('='*70)
    try:
        async with websockets.connect(URL, ping_interval=30) as ws:
            await ws.send(json.dumps(sub_payload))
            print(f"  [connected, sent subscribe, listening {listen_sec}s…]")
            n_frames = 0
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=listen_sec)
                    n_frames += 1
                    if n_frames <= 3:
                        # Decode bytes if needed; show truncated
                        if isinstance(raw, bytes):
                            try:
                                txt = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                txt = repr(raw[:200])
                        else:
                            txt = raw
                        try:
                            parsed = json.loads(txt)
                            keys = list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
                            print(f"  [frame #{n_frames}] keys={keys}")
                            print(f"     content: {json.dumps(parsed, ensure_ascii=False)[:300]}")
                        except json.JSONDecodeError:
                            print(f"  [frame #{n_frames}] raw (not JSON): {txt[:200]}")
                    if n_frames >= 3:
                        # We've got enough — wait for the listen window then report
                        await asyncio.sleep(0.5)
                        break
            except asyncio.TimeoutError:
                pass
            print(f"  [total frames received: {n_frames}]")
    except Exception as e:
        print(f"  [ERROR: {type(e).__name__}: {e}]")


async def main() -> None:
    for label, sub in CANDIDATES:
        await try_one(label, sub, listen_sec=8)


if __name__ == "__main__":
    asyncio.run(main())
