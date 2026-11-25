import numpy as np

from mm_tick.mspread import simulate_m

M, TK = 2.0, 5.0


def _run(t, px, side, pred_bid=None, c=None, eta=None, theta=None):
    n_s = 100
    pb = np.full(n_s, np.nan) if pred_bid is None else pred_bid
    el = np.full(n_s, np.nan) if eta is None else eta
    e1, w2 = np.array([0.0]), np.zeros(2)
    return simulate_m(np.asarray(t, np.int64), np.asarray(px, float), np.asarray(side, np.int8),
                      np.full(100, 0.5, np.float32), np.full(5, 5.0), 0, 0, 250, 1_800_000, M, TK, 20.0, 0.8,
                      pb, np.full(n_s, np.nan), -1e9 if c is None else c, c is not None, el, el, 0.0,
                      e1, w2, e1, w2, e1, w2, 2.0 if theta is None else theta, theta is not None)


# touch 1000 / 1001, mid 1000.5; need 5 + target 20 = 25 bp -> h = 12.5 bp = ceil(1.25) = 2 ticks:
# bid floor(998.5) = 998, ask ceil(1002.5) = 1003; long take-profit max(1003, 998 + ceil(2.495)=1001) = 1003
T = [1000, 1100, 2000, 2500, 3000]
PX = [1000, 1001, 997, 1002, 1004]
SD = [-1, 1, -1, 1, 1]


def test_wide_quote_fills_through_and_exits_at_the_other_quote():
    et, ex, pnl, tp, sd, en, tp0, dfd = _run(T, PX, SD)
    assert en[0] == 998 and sd[0] == 1 and tp0[0] == 1003 and tp[0] and ex[0] == 3000
    assert abs(pnl[0] - ((1003 - 998) / 998 * 1e4 - 4.0)) < 1e-9


def test_cancel_model_withdraws_the_bid():
    pb = np.full(100, -50.0)
    r = _run(T, PX, SD, pred_bid=pb, c=0.0)
    assert (r[4] != 1).all()                              # no long: the bid was cancelled (the ask still trades)


def test_exit_model_moves_take_profit_to_break_even():
    # P(loss) = sigmoid(10) > 0.5 at the first check (>= 1 s after entry at 2000): tp -> ceil(998 * 1.0004) = 999
    t = [1000, 1100, 2000, 3100, 3500, 3600]
    px = [1000, 1001, 997, 998, 999, 1000]
    sd = [-1, 1, -1, -1, 1, 1]
    et, ex, pnl, tp, s, en, tp0, dfd = _run(t, px, sd, eta=np.full(100, 10.0), theta=0.5)
    assert dfd[0] and tp[0] and ex[0] == 3500            # 999 is inside the touch (ask 1001): a trade at it fills
    assert abs(pnl[0] - ((999 - 998) / 998 * 1e4 - 4.0)) < 1e-9
