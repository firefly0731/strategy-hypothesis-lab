"""Performance metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def xirr(times_years: np.ndarray, flows: np.ndarray) -> float:
    """Money-weighted annual IRR. flows: investor's view (contributions < 0, final value > 0)."""
    t = np.asarray(times_years, float)
    f = np.asarray(flows, float)

    def npv(r):
        return float(np.sum(f / (1 + r) ** t))

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return np.nan
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def max_drawdown(nav: np.ndarray) -> float:
    nav = np.asarray(nav, float)
    peak = np.maximum.accumulate(nav)
    return float(np.max(1 - nav / peak))


def cagr(nav: np.ndarray, years: float) -> float:
    return float((nav[-1] / nav[0]) ** (1 / years) - 1)


def sharpe(r: np.ndarray, ppy: float = 365.0) -> float:
    r = np.asarray(r, float)
    s = r.std(ddof=1)
    return float(r.mean() / s * np.sqrt(ppy)) if s > 0 else np.nan


def tstat(r) -> float:
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r)))


def nw_ols(y: np.ndarray, X: np.ndarray, lags: int = 5):
    """OLS with Newey-West standard errors. X without constant; returns (b, t) incl. intercept."""
    Xm = np.column_stack([np.ones(len(y)), X])
    b, *_ = np.linalg.lstsq(Xm, y, rcond=None)
    e = y - Xm @ b
    XtX_inv = np.linalg.inv(Xm.T @ Xm)
    S = (Xm * e[:, None]).T @ (Xm * e[:, None])
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = (Xm[l:] * e[l:, None]).T @ (Xm[:-l] * e[:-l, None])
        S += w * (G + G.T)
    se = np.sqrt(np.diag(XtX_inv @ S @ XtX_inv))
    return b, b / se


def day_end_bars(index: pd.DatetimeIndex) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """Positions of the last bar of each UTC calendar day, and the day labels."""
    d = index.normalize()
    last = np.flatnonzero(np.r_[d[1:] != d[:-1], True])
    return last, pd.DatetimeIndex(d[last]).tz_localize(None)


def yearly_table(r: pd.Series, ppy: float = 365.0) -> pd.DataFrame:
    g = r.groupby(r.index.year)
    return pd.DataFrame({"sum": g.sum(), "n": g.size(), "sharpe": g.apply(lambda x: sharpe(x, ppy)),
                         "t": g.apply(tstat)})
