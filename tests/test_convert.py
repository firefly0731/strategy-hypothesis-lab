import json
from pathlib import Path

import polars as pl
import pytest

from observer.convert import build_dataframe, iter_jsonl_lines


def test_iter_jsonl_skips_truncated_last_line(tmp_path: Path) -> None:
    p = tmp_path / "test.jsonl"
    # Two complete lines + one truncated (no trailing newline, partial JSON)
    p.write_bytes(b'{"a":1}\n{"a":2}\n{"a":3')
    rows = list(iter_jsonl_lines(p))
    assert rows == [{"a": 1}, {"a": 2}]


def test_iter_jsonl_handles_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_bytes(b"")
    rows = list(iter_jsonl_lines(p))
    assert rows == []


def test_iter_jsonl_skips_unparseable_lines(tmp_path: Path) -> None:
    p = tmp_path / "test.jsonl"
    p.write_bytes(b'{"a":1}\nnot-json\n{"a":2}\n')
    rows = list(iter_jsonl_lines(p))
    assert rows == [{"a": 1}, {"a": 2}]


def _envelope(channel: str, raw: dict, *, server_ts_ms: int = 0, recv_monotonic_ns: int = 0) -> dict:
    return {
        "channel": channel,
        "server_ts_ms": server_ts_ms,
        "recv_monotonic_ns": recv_monotonic_ns,
        "recv_utc_ms": 0,
        "raw": raw,
    }


def test_build_dataframe_transaction_extracts_side_price_qty() -> None:
    rows = [
        _envelope(
            "transaction",
            {"content": {"list": [
                {"buySellGb": "1", "contPrice": "1380.5", "contQty": "10"},
                {"buySellGb": "2", "contPrice": "1380.0", "contQty": "5.5"},
            ]}},
            recv_monotonic_ns=100,
        )
    ]
    df = build_dataframe("transaction", rows)
    assert df.columns == ["recv_monotonic_ns", "server_ts_ms", "side", "price", "qty"]
    assert df.shape == (2, 5)
    assert df["side"].to_list() == ["buy", "sell"]
    assert df["price"].to_list() == [pytest.approx(1380.5), pytest.approx(1380.0)]


def test_build_dataframe_myorder_extracts_status_fields() -> None:
    rows = [
        _envelope(
            "myOrder",
            {"content": {
                "order_id": "abc",
                "order_status": "FILLED",
                "order_side": "BID",
                "price": "1380.0",
                "quantity": "50",
                "filled_quantity": "50",
                "timestamp": "1714287030000",
            }},
            recv_monotonic_ns=200,
        ),
    ]
    df = build_dataframe("myOrder", rows)
    assert "order_uuid" in df.columns
    assert "state" in df.columns
    assert "filled_qty" in df.columns
    assert df["order_uuid"].to_list() == ["abc"]
    assert df["state"].to_list() == ["FILLED"]
    assert df["filled_qty"].to_list() == [pytest.approx(50.0)]
