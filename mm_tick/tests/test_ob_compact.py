import gzip
import json

import pandas as pd

from mm_tick import ob_compact
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
    (4, {"stream": "xusdt@depth@0ms", "data": {"e": "depthUpdate", "E": 4, "T": 4, "s": "X", "U": 11, "u": 12,
                                               "pu": 10, "b": [["1.0", "0"]], "a": [["1.1", "1"]]}}),
]
LIQ = (5_000_000, {"stream": "xusdt@forceOrder", "data": {"e": "forceOrder", "E": 5, "o": {
    "s": "X", "S": "SELL", "o": "LIMIT", "f": "IOC", "q": "3", "p": "0.9", "ap": "0.95", "X": "FILLED",
    "l": "3", "z": "3", "T": 4}}})
MARK = (6_000_000, {"stream": "xusdt@markPrice@1s", "data": {"e": "markPriceUpdate", "E": 6, "s": "X", "p": "1.05",
                                                            "i": "1.04", "P": "1.05", "r": "0.0001", "T": 28800000}})


def test_compacts_every_stream_and_deletes_only_verified_raw(tmp_path):
    day = tmp_path / "raw" / "20200101"
    day.mkdir(parents=True)
    _write(day / "xusdt.gz", LINES + [LIQ, MARK])
    rep = compact_day(day, tmp_path / "pq", delete_raw=True)
    assert rep[0]["ok"] and rep[0]["deleted"] and not (day / "xusdt.gz").exists()
    od = tmp_path / "pq" / "20200101"
    assert len(pd.read_parquet(od / "xusdt_snap_ev.parquet")) == 1
    s = pd.read_parquet(od / "xusdt_snap_lv.parquet")
    assert list(s["px_k"]) == [10, 11, 12] and list(s["side"]) == [1, -1, -1]
    b = pd.read_parquet(od / "xusdt_bbo.parquet")
    assert b["bid_k"].iloc[0] == 10 and b["spr_k"].iloc[0] == 1 and abs(b["tick"].iloc[0] - 0.1) < 1e-12
    t = pd.read_parquet(od / "xusdt_trade.parquet")
    assert list(t["px_k"]) == [11] and t["qty"].iloc[0] == 2.0
    e = pd.read_parquet(od / "xusdt_depth_ev.parquet")
    assert list(e["u"]) == [12] and list(e["pu"]) == [10]
    d = pd.read_parquet(od / "xusdt_depth_lv.parquet")
    assert list(d["side"]) == [1, -1] and list(d["qty"]) == [0.0, 1.0] and list(d["px_k"]) == [10, 11]
    q = pd.read_parquet(od / "xusdt_liq.parquet")
    assert q["side"].iloc[0] == -1 and q["avg_px"].iloc[0] == 0.95 and q["status"].iloc[0] == "FILLED"
    m = pd.read_parquet(od / "xusdt_mark.parquet")
    assert m["mark"].iloc[0] == 1.05 and m["next_funding_T"].iloc[0] == 28800000


def test_tick_from_exchange_info_and_off_grid_price_keeps_raw(tmp_path):
    day = tmp_path / "raw" / "20200101"
    day.mkdir(parents=True)
    info = {"symbols": [{"symbol": "XUSDT", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.05"}]},
                        {"symbol": "YUSDT", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.2"}]}]}
    (day / "exchangeInfo.json").write_text(json.dumps(info))
    _write(day / "xusdt.gz", LINES)
    _write(day / "yusdt.gz", LINES)                       # 1.1 is not on the 0.2 grid
    rep = {r["sym"]: r for r in compact_day(day, tmp_path / "pq", delete_raw=True)}
    assert rep["xusdt"]["ok"]
    b = pd.read_parquet(tmp_path / "pq" / "20200101" / "xusdt_bbo.parquet")
    assert b["bid_k"].iloc[0] == 20 and b["tick"].iloc[0] == 0.05
    assert not rep["yusdt"]["ok"] and (day / "yusdt.gz").exists() and "parse" in rep["yusdt"]["error"]


def test_row_groups_keep_every_row(tmp_path, monkeypatch):
    monkeypatch.setattr(ob_compact, "CHUNK", 7)
    day = tmp_path / "raw" / "20200101"
    day.mkdir(parents=True)
    _write(day / "xusdt.gz", LINES * 50)
    rep = compact_day(day, tmp_path / "pq", delete_raw=False)
    assert rep[0]["ok"] and rep[0]["n_depth_lv"] == 100 and rep[0]["n_snap_lv"] == 150
    d = pd.read_parquet(tmp_path / "pq" / "20200101" / "xusdt_depth_ev.parquet")
    assert list(d["ev"]) == list(range(50))


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
    _write(day / "xusdt.gz", LINES + [(5, {"stream": "xusdt@kline_1m", "data": {}})])
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


def test_corrupt_member_in_the_middle_is_kept_and_does_not_stop_the_day(tmp_path):
    day = tmp_path / "raw" / "20200101"
    day.mkdir(parents=True)
    p = day / "axusdt.gz"
    _write(p, LINES * 200)
    data = p.read_bytes()
    _write(day / "tail.gz", LINES)
    p.write_bytes(data[: len(data) // 2] + (day / "tail.gz").read_bytes())   # truncated member, then a new one
    (day / "tail.gz").unlink()
    _write(day / "bxusdt.gz", LINES)
    rep = compact_day(day, tmp_path / "pq", delete_raw=True)
    assert [r["sym"] for r in rep] == ["axusdt", "bxusdt"]
    assert not rep[0]["ok"] and p.exists() and rep[1]["ok"] and rep[1]["deleted"]
