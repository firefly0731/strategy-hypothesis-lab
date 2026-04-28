"""JWT generation for Bithumb Private WebSocket v2."""
from __future__ import annotations

import uuid

import jwt as pyjwt


def make_bithumb_jwt(*, api_key: str, api_secret: str, nonce: str | None = None) -> str:
    payload = {
        "access_key": api_key,
        "nonce": nonce or str(uuid.uuid4()),
    }
    return pyjwt.encode(payload, api_secret, algorithm="HS256")
