import numpy as np

from mm_tick.grid import simulate_g

M, TK = 2.0, 5.0
W = np.log(1.005)            # band half-width: upper = anchor * 1.005, lower = anchor / 1.005


def run(trades, anchor_fn, need=30.0, max_inv=5, rule=1, zq_brk=1.0):
    """Prices in ticks (unit = 1). anchor_fn(second) -> anchor price. zq = 1, den = W."""
    t = np.array([x[0] for x in trades], np.int64)
    px = np.array([x[1] for x in trades], float)
    side = np.array([x[2] for x in trades], np.int8)
    n_s = int(t.max() // 1000) + 2
    anchor = np.log(np.array([anchor_fn(s) for s in range(n_s)], float))
    den = np.full(n_s, W, np.float32)
    return simulate_g(t, px, side, anchor, den, np.ones(1), np.full(1, zq_brk), np.full(1, need), 0, 1.0,
                      rule, max_inv, 250, M, TK)


# market bid 1000 / ask 1001; band 996..1005 around anchor 1000; need 30 bp = 3 ticks
OPEN = [(1000, 1000, -1), (1100, 1001, 1)]


def test_round_trip_at_avg_plus_need():
    # through rule: a sell at 999 fills our bid 1000; the exit ask is 1003; a buy at 1004 fills it
    et, pnl, kind, inv = run(OPEN + [(2000, 999, -1), (3000, 1004, 1)], lambda s: 1000.0)
    assert len(pnl) == 1 and kind[0] == 0
    assert abs(pnl[0] - (30.0 - 2 * M)) < 1e-9


def test_exit_ask_is_moved_down_to_the_upper_band_edge():
    # after the fill the anchor drops to 996: upper edge floor(996 * 1.005) = 1000, below
    # break-even 1003, and the exit ask follows it down (user's rule)
    a = lambda s: 1000.0 if s < 2 else 996.0
    et, pnl, kind, inv = run(OPEN + [(2000, 999, -1), (4000, 999, -1), (5000, 1001, 1)], a)
    assert len(pnl) == 1 and kind[0] == 0
    assert abs(pnl[0] - (0.0 - 2 * M)) < 1e-9                 # sold at 1000 = entry


def test_adverse_break_liquidates_all_units_by_taker():
    # two units bought (grid step 3 ticks: 1000, then 997), then a trade below the lower edge
    trades = OPEN + [(2000, 999, -1), (2100, 998, -1), (3000, 996, -1), (3100, 998, 1),
                     (4000, 990, -1)]
    et, pnl, kind, inv = run(trades, lambda s: 1000.0)
    assert len(pnl) == 2 and (kind == 1).all() and inv.max() == 2
    exp = [(990 - 1000) / 1000 * 1e4 - M - TK, (990 - 997) / 997 * 1e4 - M - TK]
    assert np.allclose(sorted(pnl), sorted(exp))


def test_inventory_limit_one_blocks_adding():
    trades = OPEN + [(2000, 999, -1), (2100, 998, -1), (3000, 996, -1), (3100, 998, 1),
                     (4000, 990, -1)]
    et, pnl, kind, inv = run(trades, lambda s: 1000.0, max_inv=1)
    assert len(pnl) == 1 and inv.max() == 1


def test_no_entry_when_the_band_leaves_no_room_for_need():
    # need 100 bp = 10 ticks, but the upper edge is only 5 ticks above the bid
    et, pnl, kind, inv = run(OPEN + [(2000, 999, -1), (3000, 1012, 1)], lambda s: 1000.0, need=100.0)
    assert len(pnl) == 0


def test_exit_after_two_units_is_on_the_tick_grid():
    # units at 1000 and 997: average 998.5, + 3 ticks = 1001.5 -> the exit ask is 1002
    trades = OPEN + [(2000, 999, -1), (2100, 998, -1), (3000, 996, -1), (4000, 1002, 1), (5000, 1003, 1)]
    et, pnl, kind, inv = run(trades, lambda s: 1000.0)
    # through rule: the trade at 1002 does not fill an ask at 1002 (an off-grid 1001.5 would);
    # the trade at 1003 does, and FIFO closes the 1000 unit
    assert kind[0] == 0
    assert np.isclose(pnl[0], (1002 - 1000) / 1000 * 1e4 - 2 * M)


def test_inventory_never_exceeds_the_limit_on_random_tape():
    rng = np.random.default_rng(1)
    n = 20_000
    t = np.cumsum(rng.integers(50, 400, n)).astype(np.int64)
    px = 1000 + np.cumsum(rng.choice([-1, 0, 0, 1], n))
    side = rng.choice([-1, 1], n).astype(np.int8)
    trades = list(zip(t, px.astype(float), side))
    for inv_max in (1, 3, 5):
        et, pnl, kind, inv = run(trades, lambda s: 1000.0, need=10.0, max_inv=inv_max, rule=0, zq_brk=3.0)
        assert len(pnl) > 0 and inv.max() <= inv_max
