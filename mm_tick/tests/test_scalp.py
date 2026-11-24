import numpy as np
import pytest

from mm_tick.scalp import simulate

T = 4.0


def run(trades, rule=0, u_val=0.5, u_on=1.0, delay=250, timeout=300_000):
    t = np.array([x[0] for x in trades], np.int64)
    px = np.array([x[1] for x in trades], float)
    side = np.array([x[2] for x in trades], np.int8)
    u = np.full(10_000, u_val, np.float32)
    return simulate(t, px, side, u, 0, 1.0, rule, u_on, delay, timeout, T)


# market: bid 100 (taker sells), ask 101 (taker buys); quotes land 250 ms later
BASE = [(1000, 100, -1), (1001, 101, 1)]


def test_touch_round_trip_takes_one_tick():
    et, pnl, tp = run(BASE + [(2000, 100, -1), (3000, 101, 1)], rule=0)
    assert len(pnl) == 1 and tp[0] and pnl[0] == pytest.approx(1 / 100 * 1e4)


def test_through_rule_needs_a_trade_beyond_the_quote():
    et, pnl, tp = run(BASE + [(2000, 100, -1), (3000, 101, 1)], rule=1)
    assert len(pnl) == 0
    et, pnl, tp = run(BASE + [(2000, 99, -1), (3000, 101, 1), (4000, 102, 1)], rule=1)
    # long at 100 (traded through by a sell at 99); TP 101 needs a buy above 101
    assert len(pnl) == 1 and tp[0] and pnl[0] == pytest.approx(100)


def test_timeout_exits_at_the_bid_with_taker_fee():
    tr = BASE + [(2000, 100, -1), (3000, 99, -1), (400_000, 98, -1)]
    et, pnl, tp = run(tr, rule=0, timeout=300_000)
    assert not tp[0]
    # timeout checked on the trade at 400 s; the bid at that moment is still 99 (updated after the check)
    assert pnl[0] == pytest.approx((99 - 100) / 100 * 1e4 - T)


def test_band_switch_blocks_entries():
    et, pnl, tp = run(BASE + [(2000, 100, -1), (3000, 101, 1)], u_val=0.97, u_on=0.95)
    assert len(pnl) == 0


def test_stale_quote_is_picked_off_before_the_update_lands():
    # the ask moves 101 -> 102 at t=1500, but our ask at 101 is still resting, so that buy fills it
    # (short at 101); the take-profit at 100 fills on the sell at 2100
    tr = BASE + [(1500, 102, 1), (2000, 101, -1), (2100, 100, -1)]
    et, pnl, tp = run(tr, rule=0)
    assert len(pnl) == 1 and tp[0] and pnl[0] == pytest.approx(1 / 101 * 1e4)


def run2(trades, rule=0, u=None, tp_bp=20.0, exit_u=2.0, u_on=1.0):
    t = np.array([x[0] for x in trades], np.int64)
    px = np.array([x[1] for x in trades], float)
    side = np.array([x[2] for x in trades], np.int8)
    uu = np.full(10_000, 0.5, np.float32) if u is None else u
    return simulate(t, px, side, uu, 0, 1.0, rule, u_on, 250, 1_800_000, T, tp_bp, exit_u)


def test_take_profit_20bp_in_ticks():
    # price 10_000 ticks: 20 bp = 20 ticks
    b = [(1000, 10_000, -1), (1001, 10_001, 1)]
    et, pnl, tp = run2(b + [(2000, 10_000, -1), (3000, 10_019, 1)])
    assert len(pnl) == 1 and not tp[0]             # 19 ticks: no take-profit (closed at the end of data)
    et, pnl, tp = run2(b + [(2000, 10_000, -1), (3000, 10_020, 1)])
    assert len(pnl) == 1 and tp[0] and pnl[0] == pytest.approx(20 / 10_000 * 1e4)


def test_band_exit_liquidates_with_taker_fee():
    u = np.full(10_000, 0.5, np.float32)
    u[4:] = 0.97                                    # band left from second 4 on
    b = [(1000, 10_000, -1), (1001, 10_001, 1)]
    tr = b + [(2000, 10_000, -1), (3500, 9_995, -1), (5500, 9_990, -1)]
    et, pnl, tp = run2(tr, u=u, exit_u=0.95)
    assert len(pnl) == 1 and not tp[0]
    # liquidated on the trade at 5.5 s (u of second 4 >= 0.95) at the bid then (9_995)
    assert pnl[0] == pytest.approx((9_995 - 10_000) / 10_000 * 1e4 - T)
    et, pnl, tp = run2(tr, u=u, exit_u=2.0)
    assert not tp[0] and pnl[0] == pytest.approx((9_990 - 10_000) / 10_000 * 1e4 - T)   # end-of-data close
