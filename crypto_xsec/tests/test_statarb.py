import numpy as np
import pandas as pd

from crypto_xsec.statarb import Params, daily_panels, run


def _panel(n_days=260, n=8, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n_days * 48, freq="30min", tz="UTC")
    syms = ["BTCUSDT"] + [f"C{i}USDT" for i in range(n - 1)]
    mkt = rng.normal(0, 0.003, len(idx))
    r = pd.DataFrame({s: mkt * rng.uniform(0.5, 1.5) + rng.normal(0, 0.003, len(idx)) for s in syms}, index=idx)
    qv = pd.DataFrame(1e9, index=idx, columns=syms)
    return pd.concat({"r": r, "qv": qv}, axis=1)


def test_daily_panels_alignment():
    P = _panel(30)
    Rs, Rp, QV = daily_panels(P)
    assert Rs.index.equals(Rp.index) and Rs.index.equals(QV.index)
    d = Rs.index[5]
    # P&L day d = 00:30 d -> 00:30 d+1 ; signal day d = 00:00 d -> 00:00 d+1
    r = P["r"]["BTCUSDT"]
    r.index = r.index.tz_convert(None)
    exp_sig = np.exp(r[d: d + pd.Timedelta(hours=23, minutes=30)].sum()) - 1
    exp_pnl = np.exp(r[d + pd.Timedelta(minutes=30): d + pd.Timedelta(days=1)].sum()) - 1
    assert np.isclose(Rs.loc[d, "BTCUSDT"], exp_sig)
    assert np.isclose(Rp.loc[d, "BTCUSDT"], exp_pnl)


def test_statarb_ignores_future_days():
    P = _panel()
    Rs, Rp, QV = daily_panels(P)
    F = pd.DataFrame(0.0, index=Rs.index, columns=Rs.columns)
    p = Params(window=60, min_hist=60, min_qv=0)
    a = run(Rs, Rp, QV, F, p)
    T = Rs.index[200]
    Rs2, Rp2 = Rs.copy(), Rp.copy()
    rng = np.random.default_rng(9)
    Rs2.loc[Rs2.index > T] = rng.normal(0, 0.05, Rs2.loc[Rs2.index > T].shape)
    Rp2.loc[Rp2.index > T] = rng.normal(0, 0.05, Rp2.loc[Rp2.index > T].shape)
    b = run(Rs2, Rp2, QV, F, p)
    # P&L of day D uses the signal of day D-1 and returns of P&L-day D, both <= T
    keep = a.index <= T
    pd.testing.assert_frame_equal(a[keep], b[keep])
    assert not np.allclose(a.loc[~keep, "net"], b.loc[~keep, "net"])
