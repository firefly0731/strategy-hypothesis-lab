"""Local-only data access (never downloads).

Reads the parquet cache written by `crypto_intraday_momentum.data` directly, so a missing
month raises instead of triggering a download. Cleaning matches `load_klines`: complete
1-minute grid, missing minutes filled flat at the previous close (`filled` = True).
Index = bar open_time (UTC); bar T covers [T, T+1m).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent.parent / "crypto_intraday_momentum" / "data_cache"


def load_klines_local(symbol: str, start: str, end: str) -> pd.DataFrame:
    """1m perp klines for [start, end] (inclusive timestamps, e.g. '2021-01-01', '2024-07-31 23:59')."""
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    parts = []
    for p in pd.period_range(t0.strftime("%Y-%m"), t1.strftime("%Y-%m"), freq="M"):
        m = p.strftime("%Y-%m")
        f = CACHE / "klines_v2" / symbol / f"{symbol}-1m-{m}.parquet"
        if f.exists():
            parts.append(pd.read_parquet(f))
            continue
        days = sorted((CACHE / "klines_daily_v2" / symbol).glob(f"{symbol}-1m-{m}-*.parquet"))
        if not days:
            continue   # not cached: silently skipped (end of sample)
        parts.extend(pd.read_parquet(d) for d in days)
    if not parts:
        raise ValueError(f"no cached klines for {symbol}")
    df = pd.concat(parts).drop_duplicates("open_time").set_index("open_time").sort_index()
    df.index = df.index.as_unit("ns") if hasattr(df.index, "as_unit") else df.index
    df = df[(df.index >= t0) & (df.index <= t1)]
    grid = pd.date_range(df.index[0], df.index[-1], freq="1min", tz="UTC")
    df = df.reindex(grid)
    df["filled"] = df["close"].isna()
    df["close"] = df["close"].ffill()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    df.index.name = "open_time"
    return df[["open", "high", "low", "close", "filled"]]


def load_funding_local(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Funding settlements (time floored to the minute, UTC) from the cache only."""
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    parts = []
    for p in pd.period_range(t0.strftime("%Y-%m"), t1.strftime("%Y-%m"), freq="M"):
        f = CACHE / "funding" / symbol / f"{symbol}-fundingRate-{p.strftime('%Y-%m')}.parquet"
        if f.exists():
            parts.append(pd.read_parquet(f))
    if not parts:
        return pd.DataFrame(columns=["time", "rate"])
    out = pd.concat(parts).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    out["time"] = out["time"].astype("datetime64[ns, UTC]")
    return out[(out["time"] >= t0) & (out["time"] <= t1)].reset_index(drop=True)


def ohlc_arrays(df: pd.DataFrame):
    return tuple(np.ascontiguousarray(df[c].to_numpy(dtype=np.float64)) for c in ("open", "high", "low", "close"))
