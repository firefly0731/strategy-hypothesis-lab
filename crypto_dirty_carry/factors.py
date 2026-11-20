"""Signals and risk estimates computed from a Snapshot (data with time ≤ t only)."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

DAY = pd.Timedelta(days=1)


def funding_carry(funding: pd.DataFrame, symbols: Iterable[str], t: pd.Timestamp,
                  lookback: pd.Timedelta, min_events: int = 2) -> pd.Series:
    """Trailing funding carry per day, from settlements s in (t - lookback, t].

    A settled rate accrues over the interval since the symbol's previous settlement, so
        carry = Σ rate_j / (s_n - s_0)   [per day]
    where s_1..s_n are the settlements in the window and s_0 is the settlement just before it.
    This is exact for any mix of 1h / 4h / 8h intervals. If s_0 is not available (first ever
    settlement), s_1 serves as the start and its rate is left out because its accrual period is
    unknown. Positive carry = longs pay (shorting collects).
    """
    out = pd.Series(np.nan, index=pd.Index(list(symbols)), dtype=float)
    if funding.empty:
        return out
    f = funding[funding["time"] <= t]                 # defensive; snapshots are already truncated
    lo = t - lookback
    for sym, g in f.groupby("symbol", sort=False):
        if sym not in out.index:
            continue
        times = pd.DatetimeIndex(g["time"])
        rates = g["rate"].to_numpy(dtype=float)
        inwin = np.flatnonzero(times > lo)
        if len(inwin) < min_events:
            continue
        first = inwin[0]
        if first > 0:
            start, num = times[first - 1], rates[first:].sum()
        else:
            start, num = times[first], rates[first + 1:].sum()
        span = (times[-1] - start) / DAY
        if span > 0:
            out[sym] = num / span
    return out


def rolling_vol(returns: pd.DataFrame, bars_per_year: float, min_obs: int, floor: float,
                fallback: str = "median") -> pd.Series:
    """Annualised standard deviation of bar returns over the given window.

    Names with fewer than `min_obs` returns get NaN, then the cross-sectional median if
    fallback == "median". Every value is floored at `floor` (so a flat price never gives 1/0).
    """
    cnt = returns.count()
    vol = returns.std(ddof=1) * np.sqrt(bars_per_year)
    vol[cnt < min_obs] = np.nan
    if fallback == "median" and vol.notna().any():
        vol = vol.fillna(vol.median())
    return vol.clip(lower=floor)


def estimate_betas(returns: pd.DataFrame, factors: pd.DataFrame, min_obs: int, ridge: float = 0.0,
                   shrinkage: float = 0.0, no_shrink: Iterable[str] = ()) -> pd.DataFrame:
    """Multivariate factor betas per name: r_i = a_i + Σ_f β_if F_f + e, on rows where the name and
    all factors are finite.

    ridge: slopes solve (X'X + λ I) β = X'y with λ = ridge · trace(X'X) / k (scale-free).
    shrinkage: β ← (1 - δ) β + δ · cross-sectional mean β (Vasicek-style). Names in
    `no_shrink` (hedge instruments, e.g. BTC on the BTC factor) are neither shrunk nor used in the mean.
    Returns a (names × factors) frame; NaN where the data are insufficient or degenerate.
    """
    names, fac = returns.columns, factors.columns
    out = pd.DataFrame(np.nan, index=names, columns=fac, dtype=float)
    k = len(fac)
    if k == 0:
        return out
    X_all = factors.to_numpy(dtype=float)
    Y_all = returns.to_numpy(dtype=float)
    fok = np.isfinite(X_all).all(axis=1)
    for c in range(len(names)):
        m = fok & np.isfinite(Y_all[:, c])
        if m.sum() < max(min_obs, k + 2):
            continue
        X, y = X_all[m], Y_all[m, c]
        Xm, ym = X - X.mean(0), y - y.mean()
        XtX = Xm.T @ Xm
        lam = ridge * np.trace(XtX) / k
        A = XtX + lam * np.eye(k)
        if np.linalg.matrix_rank(A) < k or np.trace(XtX) <= 0:
            continue
        out.iloc[c] = np.linalg.solve(A, Xm.T @ ym)
    if shrinkage > 0:
        pool = [n for n in names if n not in set(no_shrink)]
        prior = out.loc[pool].mean()
        rows = out.loc[pool].dropna(how="any").index
        out.loc[rows] = (1 - shrinkage) * out.loc[rows] + shrinkage * prior.to_numpy()
    return out
