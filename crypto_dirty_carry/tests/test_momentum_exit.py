import numpy as np
import pandas as pd

from crypto_dirty_carry.momentum_exit import breakouts, to_bar_grid
from crypto_dirty_carry.risk import RiskConfig, run_managed

from .conftest import make_data
from .test_risk import CFG


def bars30(n_days=30, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=48 * n_days, freq="30min", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
    return pd.DataFrame({"open": np.r_[100.0, c[:-1]], "close": c}, index=idx)


def test_breakout_matches_hand_computed_band():
    b = bars30()
    day = pd.Timestamp("2024-01-25", tz="UTC")
    k = b.index.get_loc(day + pd.Timedelta(hours=10))            # bar [10:00, 10:30)
    b.iloc[k, b.columns.get_loc("close")] *= 1.10                # +10% → far above UB
    ev = breakouts(b, "utc")
    m = day + pd.Timedelta(hours=10, minutes=30)                 # decision that sees this close
    assert bool(ev.loc[m, "up"]) and not bool(ev.loc[m, "down"])
    # hand computation of UB at m
    O = b["open"].loc[day]
    pc = b["close"].loc[day - pd.Timedelta(minutes=30)]
    prev = [b["close"].loc[day - pd.Timedelta(days=d) + pd.Timedelta(hours=10)] /
            b["open"].loc[day - pd.Timedelta(days=d)] - 1 for d in range(1, 15)]
    ub = max(O, pc) * (1 + np.mean(np.abs(prev)))
    assert b["close"].iloc[k] > ub


def test_band_uses_only_prior_sessions_and_no_future():
    b = bars30()
    T = pd.Timestamp("2024-01-20 12:00", tz="UTC")
    a = breakouts(b, "utc")
    b2 = b.copy()
    b2.loc[b2.index >= T, ["open", "close"]] *= 3.0              # change everything from T on
    c = breakouts(b2, "utc")
    pd.testing.assert_frame_equal(a[a.index <= T], c[c.index <= T])


def test_us_session_decisions_are_inside_nyse_hours():
    b = bars30(n_days=40)
    ev = breakouts(b, "us")
    ny = ev.index.tz_convert("America/New_York")
    mins = ny.hour * 60 + ny.minute
    assert ((mins >= 600) & (mins <= 930)).all()                 # 10:00 … 15:30 NY
    assert (ny.dayofweek < 5).all()


def test_grid_maps_to_first_bar_close_at_or_after_event():
    idx = pd.date_range("2024-01-01 01:00", periods=10, freq="1h", tz="UTC")
    ev = {"A": pd.DataFrame({"up": [True, False], "down": [False, True]},
                            index=pd.DatetimeIndex(["2024-01-01 03:00", "2024-01-01 03:30"], tz="UTC"))}
    up, dn = to_bar_grid(ev, idx, ["A", "B"])
    assert up[idx.get_loc(pd.Timestamp("2024-01-01 03:00", tz="UTC")), 0]
    assert dn[idx.get_loc(pd.Timestamp("2024-01-01 04:00", tz="UTC")), 0]
    assert up.sum() == 1 and dn.sum() == 1 and not up[:, 1].any()


def test_engine_exits_short_on_upside_break_and_waits_for_next_decision():
    d = make_data(n_days=100)
    base = run_managed(d, CFG, RiskConfig.off(timing=True))
    tg = base.schedule[-30]
    short = tg.w[list(tg.short)].idxmin()
    t_sig = tg.t + pd.Timedelta(hours=5)
    up = np.zeros(d.close.shape, dtype=bool)
    up[d.close.index.get_loc(t_sig), d.symbols.get_loc(short)] = True
    r = run_managed(d, CFG, RiskConfig.off(timing=True), exit_up=up)
    j = d.close.index.get_loc(t_sig)
    assert r.weights[short].iloc[j] < 0 and r.weights[short].iloc[j + 1] == 0
    assert r.bars["mom_exits"].iloc[j] == 1
    nxt = next(x.t for x in r.schedule if x.t > t_sig)
    held = r.weights[short].loc[(r.weights.index > t_sig) & (r.weights.index < nxt)]
    assert (held.iloc[1:] == 0).all()                            # no re-entry before the next decision
    # a long-side signal on a short position does nothing
    dn = up.copy()
    r2 = run_managed(d, CFG, RiskConfig.off(timing=True), exit_down=dn)
    pd.testing.assert_series_equal(r2.bars["equity"], base.bars["equity"])
