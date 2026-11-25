import numpy as np
import pytest

from mm_tick.xs import simulate_x

M, TK = 2.0, 5.0


def run(trades, rule=2, need=5.0, u_val=0.5, u_on=0.8, liquidate=False):
    t = np.array([x[0] for x in trades], np.int64)
    px = np.array([x[1] for x in trades], float)
    side = np.array([x[2] for x in trades], np.int8)
    u = np.full(10_000, u_val, np.float32)
    nd = np.full(5, need)
    return simulate_x(t, px, side, u, nd, 0, rule, u_on, 0.99, liquidate, 250, 1_800_000, M, TK)[:4]


# price ~1000 ticks: 1 tick = 10 bp. Market bid 1000, ask 1004 (4 ticks): we improve to 1001 / 1003
WIDE = [(1000, 1000, -1), (1001, 1004, 1)]


def test_improved_quote_fills_on_touch_under_hybrid():
    # a taker sell at 1001 hits our improved bid (we are alone there)
    et, pnl, tp, im = run(WIDE + [(2000, 1001, -1), (3000, 1003, 1)])
    assert len(pnl) == 1 and im[0] and tp[0]
    # take-profit = max(entry + need (1 tick), ask - 1 = 1003) = 1003; improved -> touch fills
    assert pnl[0] == pytest.approx((1003 - 1001) / 1001 * 1e4 - 2 * M)


def test_joined_quote_needs_a_trade_through_under_hybrid():
    tight = [(1000, 1000, -1), (1001, 1002, 1)]      # 2-tick spread: join the touch, 20 bp >= need
    et, pnl, tp, im = run(tight + [(2000, 1000, -1)])
    assert len(pnl) == 0                             # touch at our joined bid: back of the queue, no fill
    et, pnl, tp, im = run(tight + [(2000, 999, -1), (3000, 1003, 1)])
    assert len(pnl) == 1 and not im[0]


def test_spread_condition_blocks_quotes():
    tight = [(1000, 1000, -1), (1001, 1002, 1)]      # captured 2 ticks = 20 bp
    et, pnl, tp, im = run(tight + [(2000, 999, -1)], need=25.0)
    assert len(pnl) == 0


def test_band_switch_blocks_entries():
    et, pnl, tp, im = run(WIDE + [(2000, 1001, -1)], u_val=0.9, u_on=0.8)
    assert len(pnl) == 0


def test_timeout_exit_pays_maker_and_taker():
    tr = WIDE + [(2000, 1001, -1), (3000, 999, -1), (2_000_000, 998, -1)]
    et, pnl, tp, im = run(tr)
    assert not tp[0]
    assert pnl[0] == pytest.approx((999 - 1001) / 1001 * 1e4 - M - TK)


def test_effective_mult_finds_the_coarser_historical_tick():
    from mm_tick.xs import effective_mult
    day = 86_400_000
    n = 500
    t = np.r_[np.arange(n), day + np.arange(n), 2 * day + np.arange(5)].astype(np.int64)
    rng = np.random.default_rng(0)
    k = np.r_[rng.integers(100, 200, n) * 10,          # day 0: every price on the 10-tick grid
              rng.integers(1000, 2000, n),              # day 1: today's tick
              np.full(5, 1500)].astype(np.int64)        # day 2: too few trades, keeps day 1
    m = effective_mult(t, k)
    assert (m[:n] == 10).all() and (m[n:2 * n] == 1).all() and (m[2 * n:] == 1).all()


def test_side_is_reported_per_trip():
    t = np.array([1000, 1001, 2000, 3000, 4000, 5000], np.int64)
    px = np.array([1000, 1004, 1001, 1003, 1003, 1001], float)
    side = np.array([-1, 1, -1, 1, 1, -1], np.int8)
    out = simulate_x(t, px, side, np.full(10, 0.5, np.float32), np.full(5, 5.0), 0, 2, 0.8, 0.99, False,
                     250, 1_800_000, M, TK)
    assert out[4][0] == 1                      # the first trip was a long (our bid filled first)


def test_depth_quote_rests_behind_the_touch_and_needs_a_trade_through():
    from mm_tick.xs import simulate_x_full
    # touch 1000 / 1001; depth 30 bp at price 1000 -> 3 ticks: bid 997, ask 1004
    # a sell at 997 does not fill the 997 bid (no trade through it); a sell at 996 within the
    # 250 ms before the quote follows the new touch does
    t = np.array([1000, 1100, 2000, 2100, 4000], np.int64)        # u is read from the previous second
    px = np.array([1000, 1001, 997, 996, 1001], float)
    side = np.array([-1, 1, -1, -1, 1], np.int8)
    r = simulate_x_full(t, px, side, np.full(10, 0.5, np.float32), np.full(5, 5.0), 0, 2, 0.8, 0.99, False,
                        250, 1_800_000, 2.0, 5.0, 30.0)
    et, pnl, tp, im, sd, ex, en, tpp = r
    assert len(pnl) >= 1 and en[0] == 997 and sd[0] == 1 and et[0] == 2100
    assert not im[0]


def test_tp_frac_takes_part_of_the_distance_to_the_opposite_touch():
    from mm_tick.xs import simulate_x_full
    # same path as above: long at 997, opposite touch 1001 -> f = 1 target 1000, f = 0.5 target
    # 997 + ceil(0.5 * 3) = 999; need 5 bp is 1 tick, below both
    t = np.array([1000, 1100, 2000, 2100, 4000], np.int64)
    px = np.array([1000, 1001, 997, 996, 1001], float)
    side = np.array([-1, 1, -1, -1, 1], np.int8)
    args = (t, px, side, np.full(10, 0.5, np.float32), np.full(5, 5.0), 0, 2, 0.8, 0.99, False,
            250, 1_800_000, 2.0, 5.0, 30.0)
    assert simulate_x_full(*args)[7][0] == 1000
    assert simulate_x_full(*args, 0.5)[7][0] == 999
