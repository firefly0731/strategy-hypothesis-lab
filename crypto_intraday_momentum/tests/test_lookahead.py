"""Look-ahead / timing tests on synthetic 1m data spanning a US DST change."""
import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.backtest import Config, run_backtest, _order
from crypto_intraday_momentum.sessions import US, UTC, build_sessions
from crypto_intraday_momentum.signals import compute_signals


def synth(start="2024-01-15", end="2024-04-20", seed=1, trend=True):
    idx = pd.date_range(start, end, freq="1min", tz="UTC", inclusive="left")
    rng = np.random.default_rng(seed)
    r = rng.standard_t(4, len(idx)) * 4e-4
    if trend:  # inject intraday momentum regimes so trades actually happen
        day = idx.floor("D")
        drift = pd.Series(rng.normal(0, 2e-5, len(day.unique())), index=day.unique())
        r = r + drift.reindex(day).to_numpy()
    c = 40000 * np.exp(np.cumsum(r))
    o = np.concatenate([[c[0]], c[:-1]])
    spread = np.abs(rng.normal(0, 3e-4, len(idx))) * c
    h = np.maximum(o, c) + spread
    l = np.minimum(o, c) - spread
    v = rng.uniform(5, 50, len(idx))
    qv = v * (h + l + c) / 3
    df = pd.DataFrame(dict(open=o, high=h, low=l, close=c, volume=v, quote_volume=qv,
                           filled=False), index=idx)
    df.index.name = "open_time"
    return df


def perturb_from(df, T, seed=99):
    d = df.copy()
    mask = d.index >= T
    rng = np.random.default_rng(seed)
    k = rng.uniform(0.5, 1.5, mask.sum())
    for c in ("open", "high", "low", "close"):
        d.loc[mask, c] = d.loc[mask, c] * k
    d.loc[mask, "high"] = d.loc[mask, ["open", "high", "low", "close"]].max(axis=1) * 1.01
    d.loc[mask, "low"] = d.loc[mask, ["open", "high", "low", "close"]].min(axis=1) * 0.99
    d.loc[mask, "volume"] *= 7
    d.loc[mask, "quote_volume"] *= 3
    return d


@pytest.fixture(scope="module")
def df():
    return synth()


def test_us_session_follows_dst(df):
    m = build_sessions(df, US)
    st = dict(zip(m.dates.strftime("%Y-%m-%d"), m.start_utc))
    assert st["2024-03-08"] == pd.Timestamp("2024-03-08 14:30", tz="UTC")   # EST
    assert st["2024-03-11"] == pd.Timestamp("2024-03-11 13:30", tz="UTC")   # EDT
    assert "2024-03-09" not in st                                            # weekend
    assert "2024-02-19" not in st                                            # Presidents' Day


def test_decision_price_is_close_of_previous_bar(df):
    m = build_sessions(df, US)
    s = compute_signals(m)
    assert s.dec_min[0] == 30 and s.dec_min[-1] == 360          # 10:00 .. 15:30 NY
    for i in (20, 40):
        t_dec = m.start_utc[i] + pd.Timedelta(minutes=30)         # 10:00 NY
        assert s.px[i, 0] == df.loc[t_dec - pd.Timedelta(minutes=1), "close"]
        assert s.sess_open[i] == df.loc[m.start_utc[i], "open"]
        prev_last = m.start_utc[i - 1] + pd.Timedelta(minutes=389)  # 15:59 bar
        assert s.prev_close[i] == df.loc[prev_last, "close"]
        sl = df.loc[m.start_utc[i]: t_dec - pd.Timedelta(minutes=1)]
        assert np.isclose(s.vwap[i, 0], sl["quote_volume"].sum() / sl["volume"].sum())


@pytest.mark.parametrize("spec", [US, UTC])
def test_signals_ignore_future_bars(df, spec):
    m0 = build_sessions(df, spec)
    i = m0.n // 2
    T = m0.start_utc[i] + pd.Timedelta(minutes=int(compute_signals(m0).dec_min[3]))
    s0 = compute_signals(m0)
    s1 = compute_signals(build_sessions(perturb_from(df, T), spec))
    st = m0.start_utc.tz_convert(None).to_numpy().astype("datetime64[m]")
    dec_time = st[:, None] + s0.dec_min.astype("timedelta64[m]")[None, :]
    known = dec_time <= np.datetime64(T.tz_convert(None), "m")
    for name in ("px", "ub", "lb", "vwap", "sigma"):
        a, b = getattr(s0, name)[known], getattr(s1, name)[known]
        assert np.array_equal(a, b, equal_nan=True), name
    assert not np.allclose(s0.px[~known], s1.px[~known])     # perturbation did bite
    for name in ("sess_open", "prev_close", "daily_vol"):
        a, b = getattr(s0, name)[: i + 1], getattr(s1, name)[: i + 1]
        assert np.array_equal(a, b, equal_nan=True), name


@pytest.mark.parametrize("mode", ["taker", "maker"])
def test_backtest_ignores_future_bars(df, mode):
    cfg = Config(entry_mode=mode, exit_mode=mode, tick=0.1)
    m0 = build_sessions(df, US)
    r0 = run_backtest(m0, compute_signals(m0), cfg)
    assert len(r0.trades) > 20
    T = r0.trades["exit_time"].iloc[len(r0.trades) // 2] + pd.Timedelta(minutes=1)
    m1 = build_sessions(perturb_from(df, T), US)
    r1 = run_backtest(m1, compute_signals(m1), cfg)
    k = int((r0.trades["exit_time"] < T - pd.Timedelta(minutes=1)).sum())
    cols = ["entry_time", "exit_time", "side", "entry_px", "exit_px", "pnl"]
    pd.testing.assert_frame_equal(r0.trades[cols].iloc[:k], r1.trades[cols].iloc[:k])


def test_entries_never_before_decision(df):
    m = build_sessions(df, US)
    s = compute_signals(m)
    for mode in ("taker", "maker"):
        r = run_backtest(m, s, Config(entry_mode=mode, exit_mode=mode))
        mins = ((r.trades["entry_time"] - pd.DatetimeIndex(
            m.start_utc[np.searchsorted(m.dates, r.trades["date"])])) / pd.Timedelta(minutes=1))
        assert (mins >= 30).all()
        assert (r.trades["exit_time"] >= r.trades["entry_time"]).all()


def _one_session(lows, highs, last=100.0):
    idx = pd.date_range("2024-03-11 13:30", periods=390, freq="1min", tz="UTC")
    df = pd.DataFrame(dict(open=last, high=last + 1, low=last - 1, close=last, volume=1.0,
                           quote_volume=last, filled=False), index=idx)
    m = build_sessions(df, US)
    for k, (lo, hi) in enumerate(zip(lows, highs)):
        m.L[0, 31 + k], m.H[0, 31 + k] = lo, hi
    m.L[0, 30], m.H[0, 30] = last, last
    return m


def test_maker_needs_trade_through():
    cfg = Config(tick=0.5, maker_offset_ticks=1, maker_timeout=3)
    # limit = 100 - 0.5 = 99.5 ; touching 99.5 is not a fill
    m = _one_session([99.5, 99.5, 99.5], [100, 100, 100])
    assert _order(m, 0, 30, +1, "maker", 390, cfg, fallback_taker=False) is None
    m = _one_session([99.5, 99.4, 99.5], [100, 100, 100])
    f = _order(m, 0, 30, +1, "maker", 390, cfg, fallback_taker=False)
    assert f.maker and f.bar == 32 and f.price == 99.5
    # unfilled with fallback -> taker at open of the timeout bar
    m = _one_session([99.5, 99.5, 99.5], [100, 100, 100])
    f = _order(m, 0, 30, +1, "maker", 390, cfg, fallback_taker=True)
    assert not f.maker and f.bar == 33
