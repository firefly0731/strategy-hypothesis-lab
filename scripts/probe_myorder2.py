"""Final myOrder probe: subscribe with codes filter for multiple markets.

Tests the hypothesis that Bithumb v2 myOrder requires `codes` to actually emit.
Listens for 3 minutes; prints structure of first myOrder + myAsset.
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
MARKETS = ["KRW-USDT", "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]


def _types_only(payload):
    if isinstance(payload, dict):
        return {k: _types_only(v) for k, v in payload.items()}
    if isinstance(payload, list):
        if not payload:
            return []
        return [_types_only(payload[0]), f"... (len={len(payload)})"]
    return f"<{type(payload).__name__}>"


def _redact_for_print(payload):
    """Mask identifier-like and balance-like fields, keep schema-relevant ones."""
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            kl = k.lower()
            if any(s in kl for s in ("uuid", "id", "user", "account", "client_oid", "coid")):
                out[k] = f"<REDACTED:{type(v).__name__}>"
            elif any(s in kl for s in ("balance", "locked", "available", "total")):
                out[k] = f"<REDACTED:{type(v).__name__}>"
            elif kl == "code":
                out[k] = f"<REDACTED-MARKET>"  # mask which market the bot trades
            else:
                out[k] = _redact_for_print(v)
        return out
    if isinstance(payload, list):
        return [_redact_for_print(x) for x in payload]
    return payload


async def main() -> None:
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
        {"ticket": "probe-final"},
        {"type": "myOrder", "codes": MARKETS},
        {"type": "myAsset"},
        {"format": "DEFAULT"},
    ]

    print(f"[probe] subscribing to myOrder for markets: {MARKETS}")
    print(f"[probe] waiting up to 180s")
    print()

    deadline = asyncio.get_event_loop().time() + 180
    seen_types: dict[str, dict] = {}
    counts: dict[str, int] = {}

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
                continue
            if "error" in parsed:
                print(f"[server ERROR] {json.dumps(parsed)}")
                continue
            mtype = parsed.get("type", "<no-type>") if isinstance(parsed, dict) else "<not-dict>"
            counts[mtype] = counts.get(mtype, 0) + 1
            if mtype not in seen_types:
                seen_types[mtype] = parsed
                print(f"\n--- NEW TYPE: {mtype} ---")
                print("structure (values→types):")
                print(json.dumps(_types_only(parsed), indent=2))
                print()
                print("redacted (real values shown except IDs/balances/codes):")
                print(json.dumps(_redact_for_print(parsed), indent=2, default=str, ensure_ascii=False))

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"frame counts by type: {counts}")
    print(f"types observed: {list(seen_types.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
