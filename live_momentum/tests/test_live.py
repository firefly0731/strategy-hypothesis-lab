"""Phase 3 live trader against a fake Binance (no network, no keys).

FakeRest speaks the SignedRest interface. Behind it, a TapeVenue per symbol decides fills with
the same trade-through rule the paper trader uses, so on the synthetic session the live trader
must produce exactly the paper / backtest trades. The other tests script the exchange's
answers: partial fills, cancel/fill races, post-only rejects, refused orders, reconcile.
"""
import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.sessions import US, build_sessions
from live_momentum.binance_signed import BinanceError, OrderUnknown, check_key_permissions
from live_momentum.config import ACK_ENV, ConfigError, LiveConfig, RiskLimits
from live_momentum.executor import Fill
from live_momentum.history import prepare
from live_momentum.live import LiveTrader, ReconcileError, flatten_account, min_qty
from live_momentum.live_venue import LiveVenue, VenueError, fmt
from live_momentum.persistence import EventLog
from live_momentum.replay import replay_session
from live_momentum.signal_engine import session_for
from live_momentum.strategy import backtest_config
from live_momentum.tape_venue import TapeVenue
from live_momentum.tests.test_paper_integration import COLS, SYMS, Clock, _expected, drive

EXCH = {s: dict(tick=0.1, step=1e-6, market_step=1e-6, min_notional=0.0, min_qty=1e-6) for s in SYMS}


# ---------------------------------------------------------------------------- fake exchange
class FakeRest:
    """Binance-like REST over TapeVenue fill rules (one tape venue per symbol)."""

    def __init__(self, clock, start_ms, symbols=SYMS):
        self.clock, self.start_ms = clock, start_ms
        self.tape = {s: TapeVenue(start_ms, clock) for s in symbols}
        self.orders = {}           # cid -> dict
        self.pos = {s: 0.0 for s in symbols}
        self.calls = []
        self.dual = False
        self.fail_market = set()   # symbols whose market orders are refused

    # feed
    def on_trade(self, s, px, q, ts):
        self.tape[s].on_trade(px, q, ts)
        self._sync(s)

    def on_book(self, s, *a):
        self.tape[s].on_book(*a)

    def _t(self):
        return int((self.clock() - self.start_ms) // 60_000)

    def _sync(self, s):
        for f in list(self.tape[s].fills):
            o = self.orders[f.cid]
            if o["status"] != "FILLED":
                o.update(status="FILLED", executedQty=str(o["origQty"]), avgPrice=str(f.price),
                         updateTime=self.start_ms + f.bar * 60_000 + 30_000)
                self.pos[s] += o["side"] * o["origQty"]
        self.tape[s].fills.clear()

    # SignedRest interface
    def position_mode_dual(self):
        return self.dual

    def balances(self):
        return {"USDT": {"balance": 10_000.0, "available": 10_000.0, "upnl": 0.0}}

    def positions(self, symbols):
        return {s: self.pos.get(s, 0.0) for s in symbols}

    def open_orders(self, s=None):
        return [dict(clientOrderId=c, symbol=o["symbol"]) for c, o in self.orders.items()
                if o["symbol"] == s and o["status"] in ("NEW", "PARTIALLY_FILLED")]

    def new_order(self, s, side, qty, cid, *, limit=None, post_only=False, reduce_only=False):
        self.calls.append(("new", s, side, qty, cid, limit, post_only, reduce_only))
        assert cid not in self.orders, "duplicate client order id"
        assert len(cid) <= 36
        q = float(qty)
        if reduce_only:
            assert abs(self.pos[s]) + 1e-9 >= q and np.sign(self.pos[s]) == -side, "reduceOnly would open"
        o = dict(symbol=s, clientOrderId=cid, side=side, origQty=q, status="NEW", executedQty="0",
                 avgPrice="0", updateTime=self.clock())
        self.orders[cid] = o
        if limit is not None:
            self.tape[s].post_only(cid, side, q, float(limit), self._t(), reduce_only)
            if self.tape[s].resting[cid].rejected:
                del self.orders[cid]
                raise BinanceError(400, -5022, "post only rejected", "/fapi/v1/order")
            return dict(o)
        if s in self.fail_market:
            del self.orders[cid]
            raise BinanceError(400, -2019, "Margin is insufficient.", "/fapi/v1/order")
        f = self.tape[s].market(cid, side, q, self._t(), reduce_only)
        o.update(status="FILLED", executedQty=str(q), avgPrice=str(f.price))
        self.pos[s] += side * q
        return dict(o)

    def query_order(self, s, cid):
        self.calls.append(("query", s, cid))
        if cid not in self.orders:
            raise OrderUnknown(400, -2013, "Order does not exist.", "/fapi/v1/order")
        return dict(self.orders[cid])

    def cancel_order(self, s, cid):
        self.calls.append(("cancel", s, cid))
        o = self.orders.get(cid)
        if o is None:
            return None
        if o["status"] == "NEW":
            self.tape[s].cancel(cid, self._t())
            o["status"] = "CANCELED"
        return dict(o)

    def cancel_all(self, s):
        for c, o in self.orders.items():
            if o["symbol"] == s and o["status"] == "NEW":
                self.cancel_order(s, c)

    def user_trades(self, s, a, z):
        return []


class FakeLiveTrader(LiveTrader):
    """Forwards the market data to the fake exchange as well (the real exchange sees it itself)."""

    def on_trade(self, sym, price, qty, ts):
        self.rest.on_trade(sym, price, qty, ts)
        super().on_trade(sym, price, qty, ts)

    def on_book(self, sym, bid, ask, bq, aq, ts):
        self.rest.on_book(sym, bid, ask, bq, aq, ts)
        super().on_book(sym, bid, ask, bq, aq, ts)


def _live_cfg(tmp_path, **kw):
    risk = dict(max_gross_leverage=3.0, daily_max_loss_pct=0.19, max_notional_per_symbol=1e9,
                kill_switch_file=str(tmp_path / "KILL"))
    risk.update(kw.pop("risk", {}))
    return LiveConfig(mode="live", dry_run=False, risk=RiskLimits(**risk), **kw).validate()


@pytest.fixture
def ack(monkeypatch):
    monkeypatch.setenv(ACK_ENV, f"phase3-live:{dt.datetime.now(dt.timezone.utc).date()}")


@pytest.fixture(scope="module")
def grid_setup(synth_portfolio_dfs):
    """Synthetic session with prices on the 0.1 tick grid (real limits are tick-rounded)."""
    dfs = {}
    for s, df in synth_portfolio_dfs.items():
        d = df.copy()
        for c in ("open", "high", "low", "close"):
            d[c] = d[c].round(1)
        d["high"] = d[["open", "high", "low", "close"]].max(axis=1)
        d["low"] = d[["open", "high", "low", "close"]].min(axis=1)
        dfs[s] = d
    m = build_sessions(dfs["BTCUSDT"], US)
    for day in m.dates[::-1][:30]:
        reps = {s: replay_session(df, day, backtest_config(s, tick=0.1, include_funding=False))[0]
                for s, df in dfs.items()}
        if all(len(r) for r in reps.values()) and sum(len(r) for r in reps.values()) >= 4:
            break
    sess = session_for(day)
    prep = prepare(sess, dfs, {}, {s: 0.1 for s in SYMS})
    prep = dataclasses.replace(prep, sizing=dataclasses.replace(prep.sizing, g=1.0, eff={s: 0.5 for s in SYMS}))
    return dfs, sess, prep, reps


def _live(tmp_path, prep, clock, rest=None, **kw):
    start_ms = int(prep.session.start.value // 1_000_000)
    rest = rest or FakeRest(clock, start_ms)
    tr = FakeLiveTrader(_live_cfg(tmp_path, **kw), EXCH, clock, EventLog(tmp_path / "events.jsonl", clock),
                        tmp_path / "live_state.json", rest, equity=10_000.0)
    return tr, rest


def _trades(tr, sym):
    return pd.DataFrame([dataclasses.asdict(r) for r in tr.books[sym].ex.trades])


# ---------------------------------------------------------------------------- parity
def test_live_equals_backtest_replay(grid_setup, tmp_path, ack):
    dfs, sess, prep, reps = grid_setup
    clock = Clock()
    tr, rest = _live(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess)
    n = 0
    for s in SYMS:
        got, exp = _trades(tr, s), _expected(reps, sess, s)
        assert len(got) == len(exp)
        for c in ("side", "entry_bar", "exit_bar", "entry_maker", "exit_maker", "exit_reason"):
            assert list(got[c]) == list(exp[c]), (s, c)
        assert np.allclose(got["entry_px"], exp["entry_px"], rtol=0, atol=1e-6)
        assert np.allclose(got["exit_px"], exp["exit_px"], rtol=0, atol=1e-6)
        n += len(got)
        assert abs(rest.pos[s]) < 1e-9                       # flat at the close
    assert n >= 4
    cids = [c[4] for c in rest.calls if c[0] == "new"]
    assert len(cids) == len(set(cids))                       # client ids never reused


def test_every_exit_order_is_reduce_only(grid_setup, tmp_path, ack):
    dfs, sess, prep, reps = grid_setup
    clock = Clock()
    tr, rest = _live(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess)
    pos = {s: 0.0 for s in SYMS}
    for c in rest.calls:
        if c[0] != "new" or c[4] not in rest.orders or rest.orders[c[4]]["status"] != "FILLED":
            continue
        _, s, side, qty, cid, limit, post, ro = c
        reduces = pos[s] != 0 and np.sign(pos[s]) == -side
        assert ro == reduces, c
        pos[s] += side * float(qty)


# ---------------------------------------------------------------------------- start / reconcile
def test_refuses_non_flat_account_and_hedge_mode(grid_setup, tmp_path, ack):
    _, sess, prep, _ = grid_setup
    clock = Clock()
    clock.set(sess.start, 1.0)
    start_ms = int(sess.start.value // 1_000_000)
    rest = FakeRest(clock, start_ms)
    rest.pos["ETHUSDT"] = 0.5
    tr, _ = _live(tmp_path, prep, clock, rest)
    with pytest.raises(ReconcileError):
        tr.start_session(prep)
    rest2 = FakeRest(clock, start_ms)
    rest2.dual = True
    with pytest.raises(ReconcileError):
        _live(tmp_path, prep, clock, rest2)


def test_requires_ack_and_live_mode(grid_setup, tmp_path, monkeypatch):
    _, sess, prep, _ = grid_setup
    monkeypatch.delenv(ACK_ENV, raising=False)
    clock = Clock()
    with pytest.raises(PermissionError):
        _live(tmp_path, prep, clock)
    monkeypatch.setenv(ACK_ENV, f"phase2-testnet:{dt.datetime.now(dt.timezone.utc).date()}")
    with pytest.raises(PermissionError):
        _live(tmp_path, prep, clock)


def test_restart_reconciles_and_continues_without_replay(grid_setup, tmp_path, ack):
    dfs, sess, prep, reps = grid_setup
    clock = Clock()
    tr, rest = _live(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess, 1, 150)
    # a stray order with our prefix that the state does not know -> cancelled on restore
    rest.orders["lmSTRAY"] = dict(symbol="BTCUSDT", clientOrderId="lmSTRAY", side=1, origQty=1.0,
                                  status="NEW", executedQty="0", avgPrice="0", updateTime=0)
    tr2, _ = _live(tmp_path, prep, clock, rest)
    assert tr2.restore(prep)
    assert rest.orders["lmSTRAY"]["status"] == "CANCELED"
    assert tr2.risk.halted is None
    for s in SYMS:
        ex, v = tr2.books[s].ex, tr2.books[s].venue
        seen = ex.pos * ex.qty
        if ex.working is not None:                              # filled at the exchange, not yet seen
            seen += ex.working.side * v.orders[ex.working.cid].filled
        assert abs(rest.pos[s] - seen) < 1e-9
    drive(tr2, clock, dfs, sess, 160, None)                    # minutes 151..159 missed
    assert all(abs(rest.pos[s]) < 1e-9 for s in SYMS)
    ev = (tmp_path / "events.jsonl").read_text()
    assert '"skip_missed"' in ev and '"catchup_start"' not in ev


def test_restart_with_position_mismatch_flattens_and_halts(grid_setup, tmp_path, ack):
    dfs, sess, prep, reps = grid_setup
    clock = Clock()
    tr, rest = _live(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess, 1, 150)
    held = [s for s in SYMS if tr.books[s].ex.pos]
    s = held[0] if held else "SOLUSDT"
    rest.pos[s] += 0.25 if rest.pos[s] >= 0 else -0.25         # someone traded the account
    tr2, _ = _live(tmp_path, prep, clock, rest)
    assert tr2.restore(prep)
    assert tr2.risk.halted == "reconcile_mismatch"
    assert abs(rest.pos[s]) < 1e-9


# ---------------------------------------------------------------------------- order edge cases
class Scripted:
    """Minimal REST stub with scripted order states."""

    def __init__(self):
        self.orders, self.calls, self.market_resp = {}, [], None

    def new_order(self, s, side, qty, cid, *, limit=None, post_only=False, reduce_only=False):
        self.calls.append(("new", side, qty, cid, limit, reduce_only))
        if limit is None:
            if isinstance(self.market_resp, Exception):
                raise self.market_resp
            r = dict(self.market_resp or {})
            r.setdefault("status", "FILLED")
            r.setdefault("executedQty", qty)
            r.setdefault("avgPrice", "100.0")
            return r
        self.orders[cid] = dict(status="NEW", executedQty="0", avgPrice="0", updateTime=0)
        return dict(self.orders[cid])

    def query_order(self, s, cid):
        return dict(self.orders[cid])

    def cancel_order(self, s, cid):
        o = self.orders[cid]
        if o["status"] in ("NEW", "PARTIALLY_FILLED"):
            o["status"] = "CANCELED"
        return dict(o)


START = 1_700_000_000_000


def _venue(rest, min_notional=0.0):
    return LiveVenue("ETHUSDT", rest, START, lambda: START, dict(tick=0.01, step=0.001, min_notional=min_notional))


def test_maker_fill_seen_after_its_bar():
    r = Scripted()
    v = _venue(r)
    v.post_only("e1", 1, 0.02, 99.995, 3, False)
    assert r.calls[0][4] == "99.99"                           # buy limit rounded down to the tick
    r.orders["e1"].update(status="FILLED", executedQty="0.020", avgPrice="99.99", updateTime=START + 4 * 60_000 + 5)
    assert v.poll(4) == [] and v.poll(5)[0] == Fill("e1", 1, 0.02, 99.99, 4, True)
    assert v.poll(6) == []                                    # reported once


def test_partial_then_cancel_markets_only_the_rest():
    r = Scripted()
    v = _venue(r)
    v.post_only("e1", -1, 0.05, 100.0, 3, False)
    r.orders["e1"].update(status="PARTIALLY_FILLED", executedQty="0.020", avgPrice="100.0", updateTime=START)
    assert v.poll(5) == []
    v.cancel("e1", 8)
    r.market_resp = dict(avgPrice="99.0")
    f = v.market("m1", -1, 0.05, 8, False)
    assert r.calls[-1][2] == "0.030"                          # only the unfilled remainder
    assert f.qty == pytest.approx(0.05) and f.price == pytest.approx((0.02 * 100 + 0.03 * 99) / 0.05)


def test_fill_racing_the_cancel_sends_no_market_order():
    r = Scripted()
    v = _venue(r)
    v.post_only("x1", 1, 0.05, 100.0, 3, True)
    r.orders["x1"].update(status="FILLED", executedQty="0.050", avgPrice="100.0", updateTime=START + 8 * 60_000 + 1)
    v.cancel("x1", 8)                                         # the exchange says FILLED
    f = v.market("m1", 1, 0.05, 8, True)
    assert f.qty == pytest.approx(0.05) and f.maker and not [c for c in r.calls if c[4] is None]
    assert v.poll(9) == []                                    # not reported a second time


def test_small_entry_remainder_closes_the_leg_at_the_partial_qty():
    r = Scripted()
    v = _venue(r, min_notional=20.0)
    v.post_only("e1", 1, 0.3, 100.0, 3, False)
    r.orders["e1"].update(status="PARTIALLY_FILLED", executedQty="0.250", avgPrice="100.0", updateTime=START)
    v.cancel("e1", 8)
    f = v.market("m1", 1, 0.3, 8, False)                     # 0.05 * 100 = 5 < 20
    assert f.qty == pytest.approx(0.25) and not [c for c in r.calls if c[4] is None]


def test_post_only_reject_and_refused_orders():
    class Rej(Scripted):
        def new_order(self, s, side, qty, cid, **kw):
            if kw.get("limit") is not None:
                raise BinanceError(400, -5022, "post only", "/fapi/v1/order")
            return super().new_order(s, side, qty, cid, **kw)
    r = Rej()
    v = _venue(r)
    v.post_only("e1", 1, 0.05, 100.0, 3, False)
    assert v.orders["e1"].status == "REJECTED" and v.errors == 0 and v.poll(10) == []
    r.market_resp = BinanceError(400, -2019, "Margin is insufficient.", "/fapi/v1/order")
    f = v.market("m1", 1, 0.05, 8, False)                     # refused entry -> zero fill
    assert f.qty == 0 and v.errors == 1
    with pytest.raises(VenueError):
        v.market("m2", -1, 0.05, 9, True)                     # refused exit -> stop


def test_executor_treats_refused_entry_as_blocked(grid_setup, tmp_path, ack):
    dfs, sess, prep, reps = grid_setup
    clock = Clock()
    tr, rest = _live(tmp_path, prep, clock)
    tr.start_session(prep)
    rest.fail_market = set(SYMS)
    drive(tr, clock, dfs, sess)
    for s in SYMS:
        assert abs(rest.pos[s]) < 1e-9
        assert tr.books[s].ex.pos == 0
    assert not tr.emergency                                   # refused entries are not emergencies


def test_order_failure_on_exit_flattens_from_the_exchange(grid_setup, tmp_path, ack):
    dfs, sess, prep, reps = grid_setup
    clock = Clock()
    tr, rest = _live(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess, 1, 150)
    held = [s for s in SYMS if tr.books[s].ex.pos]
    assert held
    s = held[0]

    def boom(*a, **k):
        raise RuntimeError("network down")
    for b in tr.books.values():
        b.venue.market = boom
    (tmp_path / "KILL").write_text("x")                       # kill -> flatten -> market fails
    drive(tr, clock, dfs, sess, 151, 152)
    assert tr.emergency and tr.risk.halted is not None
    assert all(abs(rest.pos[x]) < 1e-9 for x in SYMS)        # flattened from exchange positions


def test_flatten_account_uses_exchange_state(tmp_path):
    clock = Clock()
    rest = FakeRest(clock, START)
    for s in SYMS:
        rest.tape[s].on_book(99.0, 101.0, 1, 1, 0)
    rest.pos.update(BTCUSDT=0.01, SOLUSDT=-2.0)
    rest.orders["lmA"] = dict(symbol="ETHUSDT", clientOrderId="lmA", side=1, origQty=1.0, status="NEW",
                              executedQty="0", avgPrice="0", updateTime=0)
    rest.tape["ETHUSDT"].post_only("lmA", 1, 1.0, 50.0, 0, False)
    out = flatten_account(rest, SYMS, EXCH)
    assert set(out) == {"BTCUSDT", "SOLUSDT"} and all(abs(v) < 1e-9 for v in rest.pos.values())
    assert rest.orders["lmA"]["status"] == "CANCELED"
    assert all(c[7] for c in rest.calls if c[0] == "new")    # reduce-only


# ---------------------------------------------------------------------------- sizing / config / key
def test_min_size_mode_and_config_rules(tmp_path):
    info = dict(tick=0.1, step=0.001, min_notional=50.0, min_qty=0.001)
    q = min_qty(info, 61_000.0)
    assert q == pytest.approx(0.001)
    q = min_qty(dict(tick=0.01, step=0.001, min_notional=20.0, min_qty=0.001), 1730.0)
    assert q * 1730 >= 20 * 1.05 and (q - 0.001) * 1730 < 20 * 1.05
    ok = _live_cfg(tmp_path, size_mode="min", risk=dict(max_gross_leverage=3.5, max_notional_per_symbol=100.0))
    assert ok.size_mode == "min"
    with pytest.raises(ConfigError):
        _live_cfg(tmp_path, risk=dict(max_gross_leverage=3.5))                     # strategy sizing <= 3x
    with pytest.raises(ConfigError):
        _live_cfg(tmp_path, size_mode="min", risk=dict(max_gross_leverage=3.5, max_notional_per_symbol=500.0))
    with pytest.raises(ConfigError):
        _live_cfg(tmp_path, size_mode="min", risk=dict(max_gross_leverage=4.5, max_notional_per_symbol=100.0))


def test_min_size_entry_is_blocked_rather_than_shrunk(grid_setup, tmp_path, ack):
    _, sess, prep, _ = grid_setup
    clock = Clock()
    exch = {s: dict(tick=0.1, step=0.001, market_step=0.001, min_notional=50.0, min_qty=0.001) for s in SYMS}
    start_ms = int(sess.start.value // 1_000_000)
    rest = FakeRest(clock, start_ms)
    tr = FakeLiveTrader(_live_cfg(tmp_path, size_mode="min", risk=dict(max_gross_leverage=1.0,
                                                                        max_notional_per_symbol=100.0)),
                        exch, clock, EventLog(tmp_path / "e.jsonl", clock), tmp_path / "s.json", rest, 100.0)
    tr.start_session(prep)
    clock.set(sess.start, 31 * 60)
    for s in SYMS:
        tr.on_trade(s, 60.0, 1.0, clock.ms)
    q = tr._qty_fn("BTCUSDT")(30, 60.0)
    assert q * 60 >= 52.5
    assert tr._gate("BTCUSDT")(30, 1, q) == pytest.approx(q)                   # 0.88 x equity: fits
    tr.books["ETHUSDT"].ex.pos, tr.books["ETHUSDT"].ex.qty = 1, 1.0             # 60 USDT open: room 40
    assert tr._gate("BTCUSDT")(30, 1, q) == 0.0                                 # would be shrunk -> blocked


def test_key_permission_rules():
    good = dict(ipRestrict=True, enableWithdrawals=False, enableFutures=True, enableInternalTransfer=False,
                permitsUniversalTransfer=False)
    assert check_key_permissions(good) == []
    assert check_key_permissions(good | dict(enableWithdrawals=True))
    assert check_key_permissions(good | dict(ipRestrict=False))
    assert check_key_permissions(good | dict(enableFutures=False))


def test_fmt_is_exact():
    assert fmt(0.013, 0.001, "floor") == "0.013" and fmt(61242.95, 0.1, "floor") == "61242.9"
    assert fmt(99.999999, 0.01, "ceil") == "100.00" and fmt(0.08, 0.01) == "0.08"


# ---------------------------------------------------------------------------- review fixes
def test_kill_with_partially_filled_entry_closes_the_exchange_residual(grid_setup, tmp_path, ack):
    dfs, sess, prep, reps = grid_setup
    clock = Clock()
    tr, rest = _live(tmp_path, prep, clock)
    tr.start_session(prep)
    # find a boundary where an entry is working, then let the exchange fill part of it
    hit = {}

    def at(t):
        def h():
            for s, b in tr.books.items():
                o = b.ex.working
                if o is not None and o.kind == "entry" and not hit:
                    rest.tape[s].resting.pop(o.cid, None)               # no further tape fills
                    part = round(o.qty / 2, 6)
                    rest.orders[o.cid].update(status="PARTIALLY_FILLED", executedQty=str(part),
                                              avgPrice=str(o.limit))
                    rest.pos[s] += o.side * part
                    hit[s] = part
                    (tmp_path / "KILL").write_text("x")
        return h
    hooks = {t: at(t) for t in range(2, sess.n_min)}
    drive(tr, clock, dfs, sess, hooks=hooks)
    assert hit, "no working entry found"
    assert all(abs(rest.pos[s]) < 1e-9 for s in SYMS)
    ev = (tmp_path / "events.jsonl").read_text()
    assert '"risk_flatten_residual"' in ev


def test_flatten_account_tries_every_symbol(tmp_path):
    clock = Clock()
    rest = FakeRest(clock, START)
    for s in SYMS:
        rest.tape[s].on_book(99.0, 101.0, 1, 1, 0)
    rest.pos.update(BTCUSDT=0.01, ETHUSDT=0.2, SOLUSDT=-2.0)
    orig = rest.cancel_all

    def cancel_all(s):
        if s == "ETHUSDT":
            raise RuntimeError("timeout")
        orig(s)
    rest.cancel_all = cancel_all
    with pytest.raises(RuntimeError, match="ETHUSDT"):
        flatten_account(rest, SYMS, EXCH)
    assert rest.pos["BTCUSDT"] == pytest.approx(0) and rest.pos["SOLUSDT"] == pytest.approx(0)


def test_signatures_are_redacted_from_logs_and_events(tmp_path):
    import logging
    from live_momentum.persistence import RedactFilter, redact
    url = "https://fapi.binance.com/fapi/v1/order?symbol=X&timestamp=1&signature=abcdef0123456789"
    assert "abcdef0123456789" not in redact(url) and "signature=***" in redact(url)
    ws = "InvalidStatus: wss://fstream.binance.com/private/ws/pqrstuvwxyz0123456789ABCDEFGH rejected"
    assert "pqrstuvwxyz0123456789" not in redact(ws) and "/ws/***" in redact(ws)
    log = EventLog(tmp_path / "e.jsonl")
    log.write("emergency_stop", error=f"ConnectionError({url!r})", nested={"x": [url]})
    assert "abcdef0123456789" not in (tmp_path / "e.jsonl").read_text()
    h = logging.FileHandler(tmp_path / "a.log", encoding="utf-8")
    h.addFilter(RedactFilter())
    lg = logging.getLogger("redact_test")
    lg.addHandler(h)
    try:
        raise ValueError(url)
    except ValueError:
        lg.exception("failed %s", url)
    h.close()
    assert "abcdef0123456789" not in (tmp_path / "a.log").read_text(encoding="utf-8")


def test_market_quantity_uses_the_market_lot_step():
    r = Scripted()
    v = LiveVenue("ETHUSDT", r, START, lambda: START, dict(tick=0.01, step=0.001, market_step=0.01, min_notional=0))
    v.market("m1", 1, 0.057, 3, False)
    assert r.calls[-1][2] == "0.05"
