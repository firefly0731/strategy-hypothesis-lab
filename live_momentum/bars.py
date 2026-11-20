"""1-minute bar handling for the live system.

The research loader (`crypto_intraday_momentum.data.load_klines`) puts klines on a complete
minute grid and fills exchange outages with flat zero-volume bars marked `filled`. The live
bar store must produce exactly the same frame, otherwise sigma / VWAP / the outage filter
would differ from the backtest. `regularize` mirrors that code; a test checks equality.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PRICE = ("open", "high", "low", "close")
VOLS = ("volume", "quote_volume", "taker_buy_volume")
ONE_MIN = pd.Timedelta(minutes=1)


def regularize(df: pd.DataFrame) -> pd.DataFrame:
    """df indexed by bar open_time (UTC) with OHLC + volume columns -> regular grid."""
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = df[[c for c in (*PRICE, *VOLS) if c in df]]
    grid = pd.date_range(df.index[0], df.index[-1], freq="1min", tz="UTC")
    df = df.reindex(grid)
    df["filled"] = df["close"].isna()
    df["close"] = df["close"].ffill()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    vol_cols = [c for c in VOLS if c in df]
    df[vol_cols] = df[vol_cols].fillna(0.0)
    df.index.name = "open_time"
    return df


def closed_before(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Bars whose close is known at `now`: open_time + 1 min <= now."""
    return df[df.index <= now - ONE_MIN]


def pad_until(df: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    """Append NaN bars (unknown future) for open_time in (last, end)."""
    start = df.index[-1] + ONE_MIN
    if start >= end:
        return df
    idx = pd.date_range(start, end, freq="1min", inclusive="left", tz="UTC")
    pad = pd.DataFrame(np.nan, index=idx, columns=df.columns)
    pad["filled"] = False
    out = pd.concat([df, pad])
    out["filled"] = out["filled"].astype(bool)
    out.index.name = df.index.name
    return out
