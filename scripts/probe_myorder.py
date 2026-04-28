"""Wait up to N minutes for a myOrder event from Bithumb v2 private WS.

Subscribes to myOrder + myAsset WITHOUT codes filter (catches all markets).
Prints first myOrder structure as soon as it arrives, then exits.
"""
from __future__ import annotations

import argparse
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


async def main(max_wait_sec: int) -> None:
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

    sub_payload = [
        {"ticket": "probe-myorder"},
        {"type": "myOrder"},
        {"type": "myAsset"},
        {"format": "DEFAULT"},
    ]

    print(f"[probe] connecting (auth via JWT)…")
    print(f"[probe] subscribe (no codes filter — catches all markets)")
    print(f"[probe] waiting up to {max_wait_sec}s for first myOrder event")
    print()

    deadline = asyncio.get_event_loop().time() + max_wait_sec
    frame_counts: dict[str, int] = {}
    seen_my_order = False

    async with websockets.connect(URL, additional_headers=headers, ping_interval=30) as ws:
        await ws.send(json.dumps(sub_payload))
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            txt = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            try:
                parsed = json.loads(txt)
            except json.JSONDecodeError:
                print(f"[non-json] {txt[:200]}")
                continue

            if "error" in parsed:
                print(f"[server ERROR] {json.dumps(parsed)}")
                continue

            mtype = parsed.get("type", "<no-type>") if isinstance(parsed, dict) else "<not-dict>"
            frame_counts[mtype] = frame_counts.get(mtype, 0) + 1

            if mtype == "myOrder" and not seen_my_order:
                seen_my_order = True
                print("=" * 70)
                print("FIRST myOrder FRAME RECEIVED")
                print("=" * 70)
                print(f"  structure (values→types):")
                print(json.dumps(_types_only(parsed), indent=2))
                # Capture this one for later analysis (gets values too, but with redaction)
                redacted = dict(parsed)
                # mask values that look identifier-like or balance-like
                # but keep status/side/timestamps/prices for schema understanding
                if isinstance(redacted, dict):
                    for k in list(redacted.keys()):
                        kl = k.lower()
                        if any(s in kl for s in ("uuid", "id", "user", "account")):
                            redacted[k] = f"<REDACTED:{type(parsed[k]).__name__}>"
                print()
                print(f"  redacted full payload (IDs masked):")
                print(json.dumps(redacted, indent=2, default=str))
                print()
                print("[probe] got first myOrder — exiting early.")
                break
            else:
                # heartbeat indicator every ~10 frames
                total = sum(frame_counts.values())
                if total % 5 == 0:
                    el = max_wait_sec - int(remaining)
                    print(f"  [t={el}s] frames so far: {dict(frame_counts)} (waiting for myOrder…)")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"frame counts by type: {dict(frame_counts)}")
    if not seen_my_order:
        print()
        print("⚠ No myOrder event captured in the wait window.")
        print("  Possible causes:")
        print("  - Bot was idle (no place/cancel/fill events) during the window")
        print("  - Bot trades a market not visible to this API key")
        print("  - Server pushes myOrder only on state TRANSITIONS (not periodic)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-wait-sec", type=int, default=180)
    args = parser.parse_args()
    asyncio.run(main(args.max_wait_sec))
