"""Raw diagnostic probe: connect to Bithumb v2 PRIVATE WS, dump field structure.

Tries the array-format subscribe (Upbit-style) and prints what comes back.
PII is redacted (values replaced with type names) before printing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
import websockets

from observer.jwt_auth import make_bithumb_jwt

URL = "wss://ws-api.bithumb.com/websocket/v1/private"


def _types_only(payload):
    if isinstance(payload, dict):
        return {k: _types_only(v) for k, v in payload.items()}
    if isinstance(payload, list):
        if not payload:
            return []
        return [_types_only(payload[0]), f"... (len={len(payload)})"]
    return f"<{type(payload).__name__}>"


async def try_one(label: str, sub_payload: list, listen_sec: int = 30) -> None:
    load_dotenv()
    api_key = os.environ.get("BITHUMB_API_KEY")
    api_secret = (
        os.environ.get("BITHUMB_API_SECRET")
        or os.environ.get("BITHUMB_SECRET_KEY")
    )
    if not api_key or not api_secret:
        sys.exit("BITHUMB_API_KEY / SECRET missing")

    token = make_bithumb_jwt(api_key=api_key, api_secret=api_secret)
    headers = [("Authorization", f"Bearer {token}")]

    print(f"\n{'='*70}")
    print(f"TRYING: {label}")
    print(f"  subscribe: {json.dumps(sub_payload)}")
    print('='*70)
    try:
        async with websockets.connect(URL, additional_headers=headers, ping_interval=30) as ws:
            await ws.send(json.dumps(sub_payload))
            print(f"  [connected (auth OK), sent subscribe, listening {listen_sec}s…]")
            n_frames = 0
            seen_types: dict[str, dict] = {}
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=listen_sec)
                    n_frames += 1
                    if isinstance(raw, bytes):
                        try:
                            txt = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            txt = repr(raw[:200])
                    else:
                        txt = raw
                    try:
                        parsed = json.loads(txt)
                        msg_type = parsed.get("type", "<no-type>") if isinstance(parsed, dict) else "<not-dict>"
                        if "error" in parsed:
                            print(f"  [frame #{n_frames}] ERROR FRAME: {json.dumps(parsed)}")
                            break
                        if msg_type not in seen_types:
                            seen_types[msg_type] = _types_only(parsed)
                            print(f"  [frame #{n_frames}] NEW TYPE: {msg_type}")
                            print(f"    structure (values→types): {json.dumps(seen_types[msg_type], indent=2)}")
                        else:
                            if n_frames <= 5:
                                print(f"  [frame #{n_frames}] (repeat type: {msg_type})")
                    except json.JSONDecodeError:
                        print(f"  [frame #{n_frames}] non-JSON: {txt[:200]}")
            except asyncio.TimeoutError:
                pass
            print(f"  [total frames received: {n_frames}]")
            print(f"  [unique types seen: {list(seen_types.keys())}]")
    except websockets.InvalidStatus as e:
        print(f"  [HTTP HANDSHAKE REJECTED: {e}]")
    except websockets.ConnectionClosed as e:
        print(f"  [WS CLOSED: code={e.code} reason={e.reason!r}]")
    except Exception as e:
        print(f"  [ERROR: {type(e).__name__}: {e}]")


async def main() -> None:
    # Candidate 1: same channel names as our current ws_private.py (myOrder, myAsset)
    await try_one(
        "myOrder + myAsset (Upbit-style names)",
        [
            {"ticket": "probe-priv-1"},
            {"type": "myOrder"},
            {"type": "myAsset"},
            {"format": "DEFAULT"},
        ],
        listen_sec=30,
    )

    # Candidate 2: with codes filter for KRW-XRP
    await try_one(
        "myOrder + myAsset with codes filter",
        [
            {"ticket": "probe-priv-2"},
            {"type": "myOrder", "codes": ["KRW-XRP"]},
            {"type": "myAsset"},
            {"format": "DEFAULT"},
        ],
        listen_sec=30,
    )


if __name__ == "__main__":
    asyncio.run(main())
