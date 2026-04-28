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


def test_build_dataframe_trade_extracts_side_price_qty() -> None:
    rows = [
        _envelope(
            "trade",
            {
                "type": "trade",
                "code": "KRW-USDT",
                "trade_price": 1380.5,
                "trade_volume": 10,
                "ask_bid": "BID",
                "timestamp": 1777351327800,
            },
            recv_monotonic_ns=100,
        ),
        _envelope(
            "trade",
            {
                "type": "trade",
                "code": "KRW-USDT",
                "trade_price": 1380.0,
                "trade_volume": 5.5,
                "ask_bid": "ASK",
                "timestamp": 1777351327900,
            },
            recv_monotonic_ns=200,
        ),
    ]
    df = build_dataframe("trade", rows)
    assert df.columns == ["recv_monotonic_ns", "server_ts_ms", "side", "price", "qty"]
    assert df.shape == (2, 5)
    assert df["side"].to_list() == ["buy", "sell"]
    assert df["price"].to_list() == [pytest.approx(1380.5), pytest.approx(1380.0)]


def test_build_dataframe_myorder_extracts_status_fields() -> None:
    rows = [
        _envelope(
            "myOrder",
            {
                "type": "myOrder",
                "code": "KRW-USDT",
                "uuid": "abc-123",
                "ask_bid": "ASK",
                "order_type": "limit",
                "state": "done",
                "price": 1485,
                "volume": 1.0,
                "remaining_volume": 0,
                "executed_volume": 1.0,
                "trades_count": 1,
                "paid_fee": 0.7425,
                "executed_funds": 1485.0,
                "trade_timestamp": 1777352061372,
                "order_timestamp": 1777349944350,
                "timestamp": 1777352061422,
            },
            recv_monotonic_ns=200,
        ),
    ]
    df = build_dataframe("myOrder", rows)
    assert "order_uuid" in df.columns
    assert "state" in df.columns
    assert "executed_qty" in df.columns
    assert df["order_uuid"].to_list() == ["abc-123"]
    assert df["state"].to_list() == ["done"]
    assert df["executed_qty"].to_list() == [pytest.approx(1.0)]
    assert df["side"].to_list() == ["sell"]


def test_convert_run_writes_parquet_and_report(tmp_path: Path) -> None:
    from observer.convert import convert_run

    # Seed a JSONL with two trade envelopes
    jsonl = tmp_path / "trade_2026-04-28T07.jsonl"
    jsonl.write_text(
        json.dumps(_envelope("trade", {
            "type": "trade", "code": "KRW-USDT",
            "trade_price": 1380.5, "trade_volume": 10, "ask_bid": "BID",
            "timestamp": 1777351327800,
        }, recv_monotonic_ns=1)) + "\n"
        + json.dumps(_envelope("trade", {
            "type": "trade", "code": "KRW-USDT",
            "trade_price": 1380.0, "trade_volume": 5, "ask_bid": "ASK",
            "timestamp": 1777351327900,
        }, recv_monotonic_ns=2)) + "\n"
    )
    # Minimal meta.json
    (tmp_path / "meta.json").write_text(json.dumps({
        "started_utc_ms": 0, "ended_utc_ms": 1000, "duration_planned_sec": 1,
        "restart_count": 0, "gaps": [], "event_counts": {"trade": 2},
        "symbol": "KRW-USDT",
    }))

    report = convert_run(tmp_path)

    parquet_path = tmp_path / "parquet" / "trade.parquet"
    assert parquet_path.exists()
    df = pl.read_parquet(parquet_path)
    assert df.shape == (2, 5)
    assert "trade" in report["event_counts"]
    assert report["event_counts"]["trade"] == 2
    assert "quality" in report
    assert report["quality"]["accumulated_gap_ms"] == 0
