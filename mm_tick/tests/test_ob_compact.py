import gzip
import json

import pandas as pd

from mm_tick.ob_compact import compact_day


def _write(path, lines):
    with gzip.open(path, "wt") as f:
        for ns, obj in lines:
            f.write(f"{ns:019d} {json.dumps(obj)}\n")


LINES = [
    (1, {"lastUpdateId": 10, "E": 1, "T": 1, "bids": [["1.0", "5"]], "asks": [["1.1", "3"], ["1.2", "4"]]}),
    (2, {"stream": "xusdt@bookTicker", "data": {"e": "bookTicker", "u": 11, "s": "X", "b": "1.0", "B": "5",
                                                "a": "1.1", "A": "3", "T": 2, "E": 2}}),
    (3, {"stream": "xusdt@aggTrade", "data": {"e": "aggTrade", "E": 3, "s": "X", "a": 7, "p": "1.1", "q": "2",
                                              "f": 1, "l": 1, "T": 3, "m": False}}),
    (4, {"stream": "xusdt@depth@100ms", "data": {"e": "depthUpdate", "E": 4, "T": 4, "s": "X", "U": 11, "u": 12,
                                                 "pu": 10, "b": [["1.0", "0"]], "a": [["1.1", "1"]]}}),
]


def test_compacts_every_stream_and_deletes_only_verified_raw(tmp_path):
    day = tmp_path / "raw" / "20200101"
    day.mkdir(parents=True)
    _write(day / "xusdt.gz", LINES)
    rep = compact_day(day, tmp_path / "pq", delete_raw=True)
    assert rep[0]["ok"] and rep[0]["deleted"] and not (day / "xusdt.gz").exists()
    od = tmp_path / "pq" / "20200101"
    assert len(pd.read_parquet(od / "xusdt_snap.parquet")) == 3
    b = pd.read_parquet(od / "xusdt_bbo.parquet")
    assert b["bid_k"].iloc[0] == 10 and b["spr_k"].iloc[0] == 1 and abs(b["tick"].iloc[0] - 0.1) < 1e-12
    assert len(pd.read_parquet(od / "xusdt_trade.parquet")) == 1
    d = pd.read_parquet(od / "xusdt_depth.parquet")
    assert list(d["side"]) == [1, -1] and list(d["qty"]) == [0.0, 1.0]


def test_truncated_gzip_is_kept(tmp_path):
    day = tmp_path / "raw" / "20200101"
    day.mkdir(parents=True)
    p = day / "xusdt.gz"
    _write(p, LINES * 200)
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])
    rep = compact_day(day, tmp_path / "pq", delete_raw=True)
    assert not rep[0]["ok"] and not rep[0]["deleted"] and p.exists()


def test_unknown_lines_block_deletion(tmp_path):
    day = tmp_path / "raw" / "20200101"
    day.mkdir(parents=True)
    _write(day / "xusdt.gz", LINES + [(5, {"stream": "xusdt@markPrice", "data": {}})])
    rep = compact_day(day, tmp_path / "pq", delete_raw=True)
    assert not rep[0]["ok"] and (day / "xusdt.gz").exists()


def test_bbo_prices_round_trip_through_ticks():
    from mm_tick.ob_compact import compact_bbo
    x = pd.DataFrame({"local_ns": [5_000_000, 9_000_000], "E": 0, "T": [3, 7], "u": 0,
                      "bid": [0.1234, 0.1236], "bid_qty": [1.5, 2.0], "ask": [0.1235, 0.1239], "ask_qty": [3.0, 4.0]})
    y = compact_bbo(x)
    assert abs(y["tick"].iloc[0] - 0.0001) < 1e-12
    assert list(y["lat_ms"]) == [2, 2]
    assert ((y["bid_k"] * y["tick"] - x["bid"]).abs() < 1e-9).all()
    assert (((y["bid_k"] + y["spr_k"]) * y["tick"] - x["ask"]).abs() < 1e-9).all()
