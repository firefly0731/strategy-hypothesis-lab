"""Replication of Heston, Korajczyk & Sadka (2010) on crypto perps.

Two estimators of the same effect (see RESEARCH_PROTOCOL.md, numerical hygiene):
  1. Fama-MacBeth average of cross-sectional slopes gamma_k,t from r_i,t = a + g * r_i,t-k
  2. Long-short spread: equal-weight top tercile minus bottom tercile of r_i,t-k, return at t
Both are in basis points per half-hour.

    python -m crypto_xsec.hks
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .panel import build_panel

LAGS = [1, 2, 3, 6, 12, 24, 46, 47, 48, 49, 50, 96, 144, 192, 240, 336, 480, 960]


def cs_slopes(R: np.ndarray, k: int, min_n: int = 10) -> np.ndarray:
    y, x = R[k:], R[:-k]
    ok = np.isfinite(y) & np.isfinite(x)
    n = ok.sum(1)
    xm = np.where(ok, x, 0).sum(1) / np.maximum(n, 1)
    ym = np.where(ok, y, 0).sum(1) / np.maximum(n, 1)
    dx = np.where(ok, x - xm[:, None], 0)
    dy = np.where(ok, y - ym[:, None], 0)
    var = (dx ** 2).sum(1)
    g = np.where((n >= min_n) & (var > 0), (dx * dy).sum(1) / np.where(var > 0, var, 1), np.nan)
    return np.concatenate([np.full(k, np.nan), g])


def tercile_spread(R: np.ndarray, k: int, min_n: int = 10) -> np.ndarray:
    y, x = R[k:], R[:-k]
    out = np.full(len(y), np.nan)
    for t in range(len(y)):
        ok = np.isfinite(y[t]) & np.isfinite(x[t])
        if ok.sum() < min_n:
            continue
        xs, ys = x[t, ok], y[t, ok]
        lo, hi = np.quantile(xs, [1 / 3, 2 / 3])
        out[t] = ys[xs >= hi].mean() - ys[xs <= lo].mean()
    return np.concatenate([np.full(k, np.nan), out])


def fm(x: np.ndarray, mask=None):
    x = x if mask is None else x[mask]
    x = x[np.isfinite(x)]
    return x.mean(), x.mean() / x.std(ddof=1) * np.sqrt(len(x)), len(x)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    P = build_panel(refresh=a.refresh)
    R = P["r"].to_numpy() * 1e4                  # bps
    idx = P.index
    ny = idx.tz_convert("America/New_York")
    us = ((ny.hour * 60 + ny.minute) >= 570) & ((ny.hour * 60 + ny.minute) < 960) & (ny.dayofweek < 5)
    print(f"panel: {R.shape[0]} half-hours x {R.shape[1]} coins, {idx[0]} .. {idx[-1]}; "
          f"median coins/obs {np.median(np.isfinite(R).sum(1)):.0f}")
    rows = []
    for k in LAGS:
        g = cs_slopes(R, k)
        sp = tercile_spread(R, k)
        gm, gt, n = fm(g / 1e4 * 1e4)          # gamma is unitless (slope); report x100
        sm, st, _ = fm(sp)
        um, ut, _ = fm(sp, us)
        rows.append(dict(lag=k, lag_days=k / 48, gamma_x100=gm * 100, gamma_t=gt,
                         spread_bps=sm, spread_t=st, spread_US_bps=um, spread_US_t=ut, n=n))
    tab = pd.DataFrame(rows).set_index("lag")
    pd.set_option("display.width", 200)
    print(tab.round(3).to_string())
    sp48 = pd.Series(tercile_spread(R, 48), index=idx)
    yr = sp48.groupby(idx.year).agg(["mean", "count", lambda x: x.mean() / x.std() * np.sqrt(x.count())])
    yr.columns = ["spread_bps", "n", "t"]
    print("\nlag-48 tercile spread by year:\n", yr.round(3).to_string())
    hr = sp48.groupby(ny.hour).agg(["mean", lambda x: x.mean() / x.std() * np.sqrt(x.count())])
    hr.columns = ["spread_bps", "t"]
    print("\nlag-48 spread by NY hour:\n", hr.round(2).T.to_string())
    tab.to_csv(P.attrs.get("out", "crypto_xsec/results/hks_lags.csv"))


if __name__ == "__main__":
    main()
