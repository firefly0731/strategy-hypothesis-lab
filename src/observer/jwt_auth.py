"""JWT generation for Bithumb Private WebSocket v2."""
from __future__ import annotations

import time
import uuid

import jwt as pyjwt


def make_bithumb_jwt(
    *,
    api_key: str,
    api_secret: str,
    nonce: str | None = None,
    timestamp_ms: int | None = None,
) -> str:
    payload = {
        "access_key": api_key,
        "nonce": nonce or str(uuid.uuid4()),
        "timestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
    }
    return pyjwt.encode(payload, api_secret, algorithm="HS256")
