"""Redact sensitive fields from captured private-channel envelopes.

Usage:
    python scripts/redact.py <input.jsonl> <output.jsonl>

Or import redact_envelope() in tests / other scripts.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

_ID_FIELDS = {
    "order_id": "REDACTED-ORDER-ID",
    "user_id": "REDACTED-USER-ID",
    "account_id": "REDACTED-ACCOUNT-ID",
}
_BALANCE_FIELDS = ("balance", "locked", "available", "total")


def redact_envelope(env: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(env)
    channel = out.get("channel")
    raw = out.get("raw") or {}
    content = raw.get("content") or {}
    if channel == "myOrder":
        for field, replacement in _ID_FIELDS.items():
            if field in content:
                content[field] = replacement
    elif channel == "myAsset":
        for field in _BALANCE_FIELDS:
            if field in content:
                content[field] = "0.0"
    return out


def _cli() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python scripts/redact.py <input.jsonl> <output.jsonl>")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    with src.open("r") as fin, dst.open("w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                env = json.loads(line)
            except json.JSONDecodeError:
                continue
            fout.write(json.dumps(redact_envelope(env)) + "\n")


if __name__ == "__main__":
    _cli()
