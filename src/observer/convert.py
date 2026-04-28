"""Post-capture JSONL → Parquet conversion + quality report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator

import polars as pl


def iter_jsonl_lines(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from a JSONL file, skipping the last line if it is
    truncated (no trailing newline) and any single-line JSON parse errors."""
    data = path.read_bytes()
    if not data:
        return
    # Determine whether the file ends with a newline.
    trailing_newline = data.endswith(b"\n")
    lines = data.splitlines()
    if not trailing_newline and lines:
        lines = lines[:-1]  # drop possibly-truncated last line
    for line in lines:
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _flatten_transaction(env: dict) -> list[dict]:
    out: list[dict] = []
    items = (env.get("raw", {}).get("content") or {}).get("list") or []
    for item in items:
        side_code = item.get("buySellGb")
        side = "buy" if str(side_code) == "1" else "sell" if str(side_code) == "2" else None
        out.append({
            "recv_monotonic_ns": env["recv_monotonic_ns"],
            "server_ts_ms": env["server_ts_ms"],
            "side": side,
            "price": _safe_float(item.get("contPrice")),
            "qty": _safe_float(item.get("contQty")),
        })
    return out


def _flatten_orderbookdepth(env: dict) -> list[dict]:
    out: list[dict] = []
    content = env.get("raw", {}).get("content") or {}
    items = content.get("list") or []
    for item in items:
        side = item.get("orderType")  # "bid" / "ask"
        out.append({
            "recv_monotonic_ns": env["recv_monotonic_ns"],
            "server_ts_ms": env["server_ts_ms"],
            "side": side,
            "price": _safe_float(item.get("price")),
            "qty": _safe_float(item.get("quantity")),
            "action": "update",  # Bithumb deltas use qty=0 to mean removal — caller can interpret
        })
    return out


def _flatten_my_order(env: dict) -> list[dict]:
    c = env.get("raw", {}).get("content") or {}
    return [{
        "recv_monotonic_ns": env["recv_monotonic_ns"],
        "server_ts_ms": env["server_ts_ms"],
        "order_uuid": c.get("order_id"),
        "state": c.get("order_status"),
        "side": c.get("order_side"),
        "price": _safe_float(c.get("price")),
        "qty": _safe_float(c.get("quantity")),
        "filled_qty": _safe_float(c.get("filled_quantity")),
        "avg_fill_price": _safe_float(c.get("avg_price")),
    }]


def _flatten_my_asset(env: dict) -> list[dict]:
    c = env.get("raw", {}).get("content") or {}
    return [{
        "recv_monotonic_ns": env["recv_monotonic_ns"],
        "server_ts_ms": env["server_ts_ms"],
        "currency": c.get("currency"),
        "balance": _safe_float(c.get("balance")),
        "locked": _safe_float(c.get("locked")),
    }]


_FLATTENERS = {
    "transaction": _flatten_transaction,
    "orderbookdepth": _flatten_orderbookdepth,
    "myOrder": _flatten_my_order,
    "myAsset": _flatten_my_asset,
}


def build_dataframe(channel: str, envelopes: Iterable[dict]) -> pl.DataFrame:
    flattener = _FLATTENERS.get(channel)
    if flattener is None:
        raise ValueError(f"unknown channel: {channel}")
    rows: list[dict] = []
    for env in envelopes:
        rows.extend(flattener(env))
    if not rows:
        # Return an empty df with correct columns by flattening one synthetic envelope.
        synth = flattener({"recv_monotonic_ns": 0, "server_ts_ms": 0, "raw": {}})
        if synth:
            cols = list(synth[0].keys())
            return pl.DataFrame({c: [] for c in cols})
        return pl.DataFrame()
    return pl.DataFrame(rows)
