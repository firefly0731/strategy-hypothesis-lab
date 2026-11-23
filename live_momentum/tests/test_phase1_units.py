"""Unit tests: tape venue fill model, risk limits, persistence, bar store, Binance parsing."""
import json

import pandas as pd
import pytest

from live_momentum.bar_store import BarStore, merged_history
from live_momentum.binance_public import AccessRestricted, PublicRest, klines_frame, ws_kline_row
from live_momentum.config import RiskLimits
from live_momentum.persistence import EventLog, atomic_write_json, read_json
from live_momentum.risk import RiskManager
from live_momentum.tape_venue import TapeVenue

T0 = 1_700_000_000_000


class Clk:
    ms = T0

    def __call__(self):
        return self.ms


def venue():
    c = Clk()
    v = TapeVenue(T0, c)
    v.on_book(99.9, 100.0, 3.0, 4.0, T0)
    return v, c


# ------------------------------------------------------------------ tape venue
def test_trade_through_fills_touch_does_not():
    v, c = venue()
    v.post_only("b1", +1, 1.0, 99.9, 0, False)            # joins the bid: queue ahead 3.0
    v.on_trade(99.9, 2.0, T0 + 10)                        # at the limit: not a fill
    assert not v.poll(10) and v.resting["b1"].at_qty == 2.0
    v.on_trade(99.8, 0.5, T0 + 70_000)                    # through, in minute 1
    assert v.poll(1) == []                                # seen only after bar 1 closes
    f = v.poll(2)
    assert len(f) == 1 and f[0].bar == 1 and f[0].price == 99.9 and f[0].maker
    h = v.history[-1]
    assert h.queue_ahead == 3.0 and h.through_qty == 0.5


def test_trades_before_the_send_do_not_fill():
    v, c = venue()
    c.ms = T0 + 5_000
    v.post_only("s1", -1, 1.0, 100.1, 0, False)
    v.on_trade(100.5, 1.0, T0 + 4_000)                    # printed before the order existed
    assert not v.poll(5)


def test_post_only_reject_when_crossing():
    v, c = venue()
    v.post_only("b2", +1, 1.0, 100.0, 0, False)           # buy at the ask -> GTX reject
    v.on_trade(99.0, 1.0, T0 + 10)
    assert not v.poll(5) and v.resting["b2"].rejected
    assert v.events[0][0] == "post_only_reject"


def test_market_at_book_or_last_when_stale():
    v, c = venue()
    assert v.market("m1", +1, 1.0, 3, False).price == 100.0
    assert v.market("m2", -1, 1.0, 3, False).price == 99.9
    v.on_trade(101.0, 1.0, T0 + 58_000)
    c.ms = T0 + 60_000                                    # book 60 s old, last trade 2 s old
    f = v.market("m3", +1, 1.0, 3, False)
    assert f.price == 101.0 and not f.maker and v.events[-1][5] == "last"
    c.ms = T0 + 120_000                                   # last trade also stale: flagged
    f = v.market("m4", -1, 1.0, 3, False)
    assert f.price == 101.0 and v.events[-1][5] == "last_stale"


def test_catchup_uses_bar_rule_and_state_roundtrip():
    v, c = venue()
    v.post_only("b3", +1, 1.0, 99.5, 4, False)
    v.on_bar_catchup(3, 99.0, 100.0)                      # before the send minute: ignored
    assert not v.fills
    st = json.loads(json.dumps(v.to_state()))
    v2, _ = venue()
    v2.load_state(st)
    v2.on_bar_catchup(5, 99.5, 100.0)                     # touching only
    assert not v2.fills
    v2.on_bar_catchup(6, 99.4, 100.0)
    assert v2.poll(7)[0].bar == 6


# ------------------------------------------------------------------ risk
def rm(tmp_path, **kw):
    lim = dict(daily_max_loss_pct=0.02, max_notional_per_symbol=0.0, max_gross_leverage=1.0,
               stale_data_sec=5.0, kill_switch_file=str(tmp_path / "KILL"))
    lim.update(kw)
    return RiskManager(RiskLimits(**lim), equity_open=10_000.0)


def test_symbol_cap_and_gross_leverage(tmp_path):
    r = rm(tmp_path, max_notional_per_symbol=3_000.0)
    q, why = r.approve_entry("BTCUSDT", 1, 1.0, 5_000.0, {}, 0.1)
    assert q * 5_000 == pytest.approx(3_000) and why == "symbol_cap"
    q, why = r.approve_entry("BTCUSDT", 1, 1.0, 2_000.0, {"ETHUSDT": 6_000, "SOLUSDT": -3_000}, 0.1)
    assert q * 2_000 == pytest.approx(1_000) and why == "gross_leverage"
    q, why = r.approve_entry("BTCUSDT", 1, 1.0, 2_000.0, {"ETHUSDT": 10_000}, 0.1)
    assert q == 0
    # the symbol's own open exposure counts too
    q, why = r.approve_entry("BTCUSDT", 1, 1.0, 2_000.0, {"BTCUSDT": 9_000}, 0.1)
    assert q * 2_000 == pytest.approx(1_000) and why == "gross_leverage"


def test_unknown_exposure_blocks_entries(tmp_path):
    r = rm(tmp_path)
    assert r.approve_entry("BTCUSDT", 1, 0.1, 1_000.0, {"ETHUSDT": float("nan")}, 0.1) == (0.0, "unknown_exposure")


def test_stale_clock_kill_and_loss(tmp_path):
    r = rm(tmp_path)
    assert r.approve_entry("BTCUSDT", 1, 0.1, 1_000.0, {}, 6.0) == (0.0, "stale_data")
    r.clock_offset_ms = 2_000
    assert r.approve_entry("BTCUSDT", 1, 0.1, 1_000.0, {}, 0.1)[1] == "clock_offset"
    r.clock_offset_ms = 0
    (tmp_path / "KILL").write_text("x")
    assert r.approve_entry("BTCUSDT", 1, 0.1, 1_000.0, {}, 0.1)[1] == "kill_switch"
    (tmp_path / "KILL").unlink()
    assert not r.check_loss(-199.0)
    assert r.check_loss(-200.0) and r.halted == "daily_loss"
    assert r.approve_entry("BTCUSDT", 1, 0.1, 1_000.0, {}, 0.1) == (0.0, "daily_loss")


# ------------------------------------------------------------------ persistence
def test_atomic_json_and_eventlog_refuses_secrets(tmp_path):
    atomic_write_json(tmp_path / "a" / "s.json", {"x": 1})
    assert read_json(tmp_path / "a" / "s.json") == {"x": 1}
    assert read_json(tmp_path / "missing.json") is None
    log = EventLog(tmp_path / "e.jsonl", lambda: 5)
    log.write("ok", sym="BTCUSDT", px=1.0)
    with pytest.raises(ValueError):
        log.write("bad", info={"api_secret": "x"})
    assert [e["type"] for e in log.read()] == ["ok"]


# ------------------------------------------------------------------ bars
def _bars(start, n, px=100.0):
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC", name="open_time")
    return pd.DataFrame(dict(open=px, high=px + 1, low=px - 1, close=px, volume=1.0, quote_volume=px,
                             taker_buy_volume=0.5), index=idx)


def test_bar_store_roundtrip_and_missing(tmp_path):
    st = BarStore(tmp_path, "BTCUSDT")
    df = _bars("2026-11-19 23:58", 4).drop(index=pd.Timestamp("2026-11-20 00:00", tz="UTC"))
    st.add_frame(df)
    st.flush()
    st2 = BarStore(tmp_path, "BTCUSDT")
    st2.load()
    assert len(st2.frame()) == 3
    assert st2.missing(pd.Timestamp("2026-11-19 23:58", tz="UTC"), pd.Timestamp("2026-11-20 00:02", tz="UTC")) \
        == [pd.Timestamp("2026-11-20 00:00", tz="UTC")]
    assert len(list((tmp_path / "bars" / "BTCUSDT").glob("*.parquet"))) == 2   # one file per UTC day


def test_merged_history_archive_wins_and_keeps_filled():
    arch = _bars("2026-11-18 00:00", 10)
    arch["filled"] = False
    arch.iloc[3, arch.columns.get_loc("filled")] = True
    live = _bars("2026-11-18 00:05", 10, px=200.0)
    m = merged_history(arch, live)
    assert (m.loc[:"2026-11-18 00:09", "close"] == 100.0).all()          # archive precedence
    assert (m.loc["2026-11-18 00:10":, "close"] == 200.0).all()
    assert m["filled"].iloc[3] and m["filled"].sum() == 1


# ------------------------------------------------------------------ binance parsing
def test_klines_frame_drops_unclosed_and_ws_row():
    rows = [[T0, "1", "2", "0.5", "1.5", "10", T0 + 59_999, "15", 3, "4", "6", "0"],
            [T0 + 60_000, "1.5", "2", "1", "1.8", "5", T0 + 119_999, "8", 2, "2", "3", "0"]]
    df = klines_frame(rows, now_ms=T0 + 100_000)
    assert len(df) == 1 and df["quote_volume"].iloc[0] == 15.0 and df["taker_buy_volume"].iloc[0] == 4.0
    t, r = ws_kline_row({"t": T0, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "q": "15", "V": "4"})
    assert t == pd.Timestamp(T0, unit="ms", tz="UTC") and r["close"] == 1.5


class _Resp:
    def __init__(self, code):
        self.status_code, self.headers = code, {}

    def json(self):
        return {}

    def raise_for_status(self):
        pass


class _Sess:
    def __init__(self, code):
        self.code, self.headers = code, {}

    def get(self, *a, **k):
        return _Resp(self.code)


@pytest.mark.parametrize("code", [403, 451])
def test_access_restricted_is_not_retried(code):
    with pytest.raises(AccessRestricted):
        PublicRest(session=_Sess(code)).get("/fapi/v1/time")


def test_eventlog_skips_truncated_line(tmp_path):
    from live_momentum.persistence import EventLog
    p = tmp_path / "e.jsonl"
    log = EventLog(p)
    log.write("a", x=1)
    with p.open("a", encoding="utf-8") as f:
        f.write('{"ts": 1, "type": "b", "x"')          # killed mid-write
    assert [e["type"] for e in EventLog(p).read()] == ["a"]


def test_eventlog_rejects_secret_at_any_depth(tmp_path):
    import pytest
    from live_momentum.persistence import EventLog
    deep = {"api_key": "x"}
    for _ in range(10):
        deep = {"a": deep}
    with pytest.raises(Exception):
        EventLog(tmp_path / "e.jsonl").write("t", d=deep)


def test_ws_handshake_status_is_read_from_websockets_exceptions():
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    from live_momentum.binance_public import ws_status
    for code in (403, 451):
        assert ws_status(InvalidStatus(Response(code, "x", Headers()))) == code
    assert ws_status(OSError("connection reset")) is None
