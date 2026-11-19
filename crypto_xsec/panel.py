"""30-minute return panel across the candidate universe (24/7, UTC grid).

A 30-min bar labelled T covers [T, T+30m). Its return is close(T+29m bar) / close(T-1m bar) - 1,
known at T+30m. Intervals that contain synthetic (outage) 1m bars are NaN.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from crypto_intraday_momentum.data import load_klines
from crypto_intraday_momentum.universe import CANDIDATES

CACHE = Path(__file__).resolve().parent / "results" / "panel30.parquet"


def returns_30m(sym: str, start: str, end: str) -> pd.DataFrame:
    df = load_klines(sym, start, end)
    g = df.resample("30min", label="left", closed="left")
    close = g["close"].last()
    bad = g["filled"].sum() > 0
    r = np.log(close).diff()
    r[bad | bad.shift(1, fill_value=False)] = np.nan
    qv = g["quote_volume"].sum()
    return pd.DataFrame({"r": r, "qv": qv})


def build_panel(start="2021-01", end="2026-10", symbols=CANDIDATES, refresh=False):
    if CACHE.exists() and not refresh:
        return pd.read_parquet(CACHE)
    parts = {}
    for s in symbols:
        try:
            parts[s] = returns_30m(s, start, end)
        except ValueError:
            continue
    R = pd.concat({s: p["r"] for s, p in parts.items()}, axis=1)
    Q = pd.concat({s: p["qv"] for s, p in parts.items()}, axis=1)
    out = pd.concat({"r": R, "qv": Q}, axis=1)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(CACHE)
    return out
