"""Perturbation (look-ahead) tests and fill-model unit tests for crypto_range."""
import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.sessions import US, build_sessions
from crypto_intraday_momentum.tests.test_lookahead import perturb_from, synth

from crypto_range.engine import Exec, Orders, simulate
from crypto_range.strategies import GRID, IDEAS, SPECS, variance_ratio


@pytest.fixture(scope="module")
def df():
    return synth("2023-11-01", "2024-04-20", trend=False)


def _run(df, idea, params, mode):
    m = build_sessions(df, SPECS[idea])
    o = IDEAS[idea](m, df=df, **params)
    return m, o, simulate(m, o, Exec(mode=mode))


CASES = [(idea, p) for idea in "ABCDEF"
         for p in (GRID[idea][0], GRID[idea][1 if idea in "EF" else -1])]


@pytest.mark.parametrize("mode", ["taker", "maker"])
@pytest.mark.parametrize("idea,params", CASES)
def test_trades_ignore_future_bars(df, idea, params, mode):
    m0, o0, t0 = _run(df, idea, params, mode)
    assert len(t0) >= 6, (idea, len(t0))
    T = t0["exit_time"].iloc[len(t0) // 2] + pd.Timedelta(minutes=1)
    d1 = perturb_from(df, T)
    m1, o1, t1 = _run(d1, idea, params, mode)
    # 1) orders decided before T are identical
    st = m0.start_utc.tz_convert(None).to_numpy().astype("datetime64[m]")
    dec = st[:, None] + o0.dec_min.astype("timedelta64[m]")[None, :]
    known = dec <= np.datetime64(T.tz_convert(None), "m")
    for name in ("side", "target", "stop", "tstop"):
        a, b = getattr(o0, name)[known], getattr(o1, name)[known]
        assert np.array_equal(a, b, equal_nan=True), name
    # 2) all trades closed before T are identical
    k = int((t0["exit_time"] < T - pd.Timedelta(minutes=1)).sum())
    cols = ["entry_time", "exit_time", "side", "entry_px", "exit_px", "net"]
    pd.testing.assert_frame_equal(t0[cols].iloc[:k].reset_index(drop=True),
                                  t1[cols].iloc[:k].reset_index(drop=True))
    assert not t0[cols].iloc[k:].reset_index(drop=True).equals(t1[cols].iloc[k:].reset_index(drop=True))


def test_variance_ratio_is_prior_only(df):
    m0 = build_sessions(df, US)
    i = m0.n // 2
    m1 = build_sessions(perturb_from(df, m0.start_utc[i]), US)
    a, b = variance_ratio(m0), variance_ratio(m1)
    assert np.array_equal(a[: i + 1], b[: i + 1], equal_nan=True)
    assert not np.allclose(a[i + 2:], b[i + 2:])


def test_entries_never_before_decision(df):
    for idea in "ABCDEF":
        for mode in ("taker", "maker"):
            m, o, t = _run(df, idea, GRID[idea][0], mode)
            assert (t["entry_bar"] >= t["dec_min"]).all()
            assert (t["exit_bar"] >= t["entry_bar"]).all()
            mk = t["entry_maker"]
            assert (t.loc[mk, "exit_bar"] > t.loc[mk, "entry_bar"]).all()
            # one position at a time per symbol
            s = t.sort_values("entry_time")
            assert (s["entry_time"].iloc[1:].to_numpy() >= s["exit_time"].iloc[:-1].to_numpy()).all()


# ----------------------------------------------------------------------------- fill model

def _session(n=390, last=100.0):
    idx = pd.date_range("2024-03-11 13:30", periods=n, freq="1min", tz="UTC")
    d = pd.DataFrame(dict(open=last, high=last + 0.05, low=last - 0.05, close=last, volume=1.0,
                          quote_volume=last, filled=False), index=idx)
    return build_sessions(d, US, n_pre=0)


def _one(m, side, t, target=np.nan, stop=np.nan, tstop=100):
    nd = 1
    return Orders(np.array([t]), np.full((1, nd), side, np.int8), np.full((1, nd), target),
                  np.full((1, nd), stop), np.full((1, nd), tstop))


def test_maker_entry_needs_trade_through():
    ex = Exec(mode="maker", maker_offset_bps=0.0, include_funding=False)
    m = _session()
    m.H[0, 30:36] = 100.0                  # sell limit at 100 is only touched
    t = simulate(m, _one(m, -1, 30, tstop=100), ex)
    assert len(t) == 0
    m.H[0, 33] = 100.01                    # traded through on bar 33
    t = simulate(m, _one(m, -1, 30, tstop=100), ex)
    assert len(t) == 1 and t["entry_bar"].iloc[0] == 33 and t["entry_px"].iloc[0] == 100.0


def test_maker_target_not_in_entry_bar_and_stop_first():
    ex = Exec(mode="maker", maker_offset_bps=0.0, include_funding=False)
    m = _session()
    m.L[0, 30] = 99.0                     # buy fills on bar 30 and the same bar trades 99..
    m.H[0, 30] = 101.0                    # ..101: target 100.5 must NOT count on bar 30
    t = simulate(m, _one(m, +1, 30, target=100.5, tstop=100), ex)
    assert t["reason"].iloc[0] == "time"
    m.H[0, 40] = 100.6
    t = simulate(m, _one(m, +1, 30, target=100.5, tstop=100), ex)
    assert t["reason"].iloc[0] == "target" and t["exit_bar"].iloc[0] == 40
    assert np.isclose(t["net"].iloc[0], 100.5 / 100 - 1 - 2e-4 - 2e-4 * 100.5 / 100)
    # stop seen on the close of bar 35 -> taker at the open of bar 36, before the target
    m.C[0, 35] = 99.0
    t = simulate(m, _one(m, +1, 30, target=100.5, stop=99.5, tstop=100), ex)
    assert t["reason"].iloc[0] == "stop" and t["exit_bar"].iloc[0] == 36
    assert not t["exit_maker"].iloc[0]


def test_taker_costs():
    ex = Exec(mode="taker", include_funding=False)
    m = _session()
    t = simulate(m, _one(m, +1, 30, tstop=60), ex)
    r = t.iloc[0]
    assert r["entry_bar"] == 30 and r["exit_bar"] == 60 and r["reason"] == "time"
    assert np.isclose(r["entry_px"], 100 * 1.0001) and np.isclose(r["exit_px"], 100 * 0.9999)
    assert np.isclose(r["net"], 0.9999 / 1.0001 - 1 - 5e-4 - 5e-4 * 0.9999 / 1.0001)
