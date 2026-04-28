import json
from pathlib import Path

from scripts.redact import redact_envelope


def test_redact_my_order_strips_identifiers() -> None:
    env = {
        "channel": "myOrder",
        "server_ts_ms": 1,
        "recv_monotonic_ns": 2,
        "recv_utc_ms": 3,
        "raw": {
            "type": "myOrder",
            "content": {
                "order_id": "secret-order-uuid-7777",
                "order_status": "FILLED",
                "order_side": "BID",
                "price": "1380.0",
                "quantity": "50",
                "filled_quantity": "50",
                "user_id": "real-user-12345",
                "account_id": "real-account-9999",
            },
        },
    }
    out = redact_envelope(env)
    assert out["raw"]["content"]["order_id"] == "REDACTED-ORDER-ID"
    assert out["raw"]["content"]["user_id"] == "REDACTED-USER-ID"
    assert out["raw"]["content"]["account_id"] == "REDACTED-ACCOUNT-ID"
    # Non-sensitive fields preserved
    assert out["raw"]["content"]["order_status"] == "FILLED"
    assert out["raw"]["content"]["price"] == "1380.0"


def test_redact_my_asset_zeros_balances() -> None:
    env = {
        "channel": "myAsset",
        "server_ts_ms": 1,
        "recv_monotonic_ns": 2,
        "recv_utc_ms": 3,
        "raw": {
            "type": "myAsset",
            "content": {"currency": "USDT", "balance": "12345.67", "locked": "100.0"},
        },
    }
    out = redact_envelope(env)
    assert out["raw"]["content"]["currency"] == "USDT"
    assert out["raw"]["content"]["balance"] == "0.0"
    assert out["raw"]["content"]["locked"] == "0.0"


def test_redact_public_passes_through() -> None:
    env = {
        "channel": "transaction",
        "server_ts_ms": 1,
        "recv_monotonic_ns": 2,
        "recv_utc_ms": 3,
        "raw": {"type": "transaction", "content": {"list": [{"contPrice": "1"}]}},
    }
    out = redact_envelope(env)
    assert out == env  # public events have no PII
