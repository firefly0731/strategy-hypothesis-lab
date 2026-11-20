"""Phase 0: per-session sizing multipliers computed before the open must reproduce the
research portfolio (build_portfolio + drawdown_throttle) session by session, and must not
depend on any bar at or after the session open."""
import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.run_sizing import build_portfolio
from crypto_intraday_momentum.sessions import US, build_sessions
from crypto_intraday_momentum.signals import compute_signals
from crypto_intraday_momentum.sizing import drawdown_throttle, pre_open_rv, unit_trades
from live_momentum.bars import pad_until
from live_momentum.signal_engine import session_for
from live_momentum.sizing_live import session_sizing
from live_momentum.strategy import SizingParams, backtest_config

from .conftest import real_data

P = SizingParams()


def build_data(dfs, funding=None):
    """funding: {sym: DataFrame(time, rate)} or None (funding off)."""
    data = {}
    for sym, df in dfs.items():
        m = build_sessions(df, US)
        f = None if funding is None else funding[sym]
        t = unit_trades(m, compute_signals(m), backtest_config(sym, include_funding=f is not None), f)
        data[sym] = (m, t, pre_open_rv(df, m))
    return data


def synth_funding(df, seed):
    """8-hourly settlements with a positive mean rate, like perpetual funding."""
    rng = np.random.default_rng(seed)
    t = pd.date_range(df.index[0].ceil("8h"), df.index[-1], freq="8h")
    return pd.DataFrame({"time": t, "rate": rng.normal(1e-4, 3e-4, len(t))})


def expected_returns(data):
    out, _ = build_portfolio(data, "rv24", "equal", P.target_ann, P.max_lev)
    return drawdown_throttle(out, P.dd_max, P.dd_floor)[0]


def live_return(data, day):
    sz = session_sizing(data, day)
    r = 0.0
    for sym, (m, t, _) in data.items():
        if t.empty:
            continue
        d = pd.DatetimeIndex(m.dates[t["sess_idx"].to_numpy()])
        r += float((sz.multiplier(sym) * t.loc[np.asarray(d == day), "ret_notional"]).sum())
    return r, sz


def check(data, days):
    exp = expected_returns(data)
    gs, scales = [], []
    for day in days:
        r, sz = live_return(data, day)
        assert np.isclose(r, exp[day], rtol=1e-9, atol=1e-13), (day, r, exp[day])
        assert 0.25 <= sz.g <= 1.0 and 0 <= sz.scale <= P.scale_cap
        assert all(0 <= e <= P.max_lev for e in sz.eff.values())
        gs.append(sz.g)
        scales.append(sz.scale)
    return np.array(gs), np.array(scales), exp


def truncated_data(dfs, day, funding=None):
    """Rebuild everything from klines (and funding) cut at the session open."""
    sess = session_for(day)
    cut = {s: pad_until(df[df.index < sess.start], sess.end) for s, df in dfs.items()}
    fcut = None if funding is None else {s: f[f["time"] < sess.start] for s, f in funding.items()}
    return build_data(cut, fcut)


@pytest.fixture(scope="module")
def synth_funding_all(synth_portfolio_dfs):
    return {s: synth_funding(df, k) for k, (s, df) in enumerate(synth_portfolio_dfs.items())}


@pytest.mark.parametrize("with_funding", [False, True])
def test_sizing_parity_synthetic(synth_portfolio_dfs, synth_funding_all, with_funding):
    data = build_data(synth_portfolio_dfs, synth_funding_all if with_funding else None)
    if with_funding:
        assert any((t["funding"] != 0).any() for _, t, _ in data.values())
    days = next(iter(data.values()))[0].dates[-60:]
    gs, scales, exp = check(data, days)
    assert (scales > 0).all()
    assert (exp.loc[days] != 0).sum() > 20


def test_sizing_parity_when_cap_and_throttle_bind(synth_portfolio_dfs):
    """Stress the inputs so that the 3x cap and the drawdown throttle both bind."""
    data = build_data(synth_portfolio_dfs)
    m, t, rv = data["BTCUSDT"]
    data["BTCUSDT"] = (m, t, rv * 0.01)                       # tiny RV24 -> huge leverage -> 3x cap
    m, t, rv = data["ETHUSDT"]
    t = t.copy()
    dates = pd.DatetimeIndex(m.dates[t["sess_idx"].to_numpy()])
    lo, hi = m.dates[-60], m.dates[-40]
    t.loc[np.asarray((dates >= lo) & (dates < hi)), "ret_notional"] = -0.004   # losing streak
    data["ETHUSDT"] = (m, t, rv)
    days = m.dates[-60:]
    gs, _, _ = check(data, days)
    assert gs.min() < 0.9                                      # throttle engaged
    caps = [session_sizing(data, d).eff["BTCUSDT"] for d in days[::10]]
    assert max(caps) == P.max_lev


def test_sizing_uses_only_pre_open_data(synth_portfolio_dfs, synth_funding_all):
    full = build_data(synth_portfolio_dfs, synth_funding_all)
    for day in next(iter(full.values()))[0].dates[[-40, -5]]:
        a = session_sizing(full, day)
        b = session_sizing(truncated_data(synth_portfolio_dfs, day, synth_funding_all), day)
        assert a.g == b.g and a.dd == b.dd
        assert np.isclose(a.scale, b.scale, rtol=1e-12)
        for s in a.eff:
            assert a.lev[s] == b.lev[s] and np.isclose(a.eff[s], b.eff[s], rtol=1e-12)


@pytest.fixture(scope="module")
def real_funding(real_dfs):
    from crypto_intraday_momentum.data import load_funding
    from .conftest import REAL_END, REAL_START
    return {s: load_funding(s, REAL_START, REAL_END) for s in real_dfs}


@real_data
def test_sizing_parity_real_last_60_sessions(real_dfs, real_funding):
    data = build_data(real_dfs, real_funding)            # funding on, as in the research
    days = next(iter(data.values()))[0].dates[-60:]
    gs, scales, exp = check(data, days)
    assert gs.min() < 1.0                                  # the throttle is active on real data
    last = session_sizing(data, days[-1])
    print(f"\nsizing parity on {len(days)} sessions {days[0].date()}..{days[-1].date()}: "
          f"g range {gs.min():.3f}..{gs.max():.3f}, scale range {scales.min():.2f}..{scales.max():.2f}; "
          f"{days[-1].date()}: dd={last.dd:.2%} g={last.g:.2f} scale={last.scale:.2f} "
          f"eff={ {k: round(v, 3) for k, v in last.eff.items()} }")


@real_data
def test_sizing_real_uses_only_pre_open_data(real_dfs, real_funding):
    full = build_data(real_dfs, real_funding)
    day = next(iter(full.values()))[0].dates[-1]
    a = session_sizing(full, day)
    b = session_sizing(truncated_data(real_dfs, day, real_funding), day)
    assert a.g == b.g and np.isclose(a.scale, b.scale, rtol=1e-12)
    for s in a.eff:
        assert a.lev[s] == b.lev[s] and np.isclose(a.eff[s], b.eff[s], rtol=1e-12)
