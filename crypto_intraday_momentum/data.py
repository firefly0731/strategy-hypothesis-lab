"""Binance USDT-M futures public data (data.binance.vision): download + load.

Kline timestamp convention (verified on the raw files):
    open_time  = start of the bar, UTC, epoch ms (μs in some newer files)
    close_time = open_time + 59.999 s
A bar with open_time T contains trades in [T, T+1min). Its close is only
known at T+1min. Everything downstream relies on this convention.
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um/monthly"
DAILY = "https://data.binance.vision/data/futures/um/daily"
DEFAULT_CACHE = Path(__file__).resolve().parent / "data_cache"

KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def _months(start: str, end: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def _to_utc(ts: pd.Series) -> pd.DatetimeIndex:
    ts = ts.astype("int64")
    # newer archives may use microseconds
    unit = np.where(ts > 10**14, "us", "ms")
    if (unit == "us").all():
        return pd.to_datetime(ts, unit="us", utc=True)
    if (unit == "ms").all():
        return pd.to_datetime(ts, unit="ms", utc=True)
    ms = ts.where(ts <= 10**14, ts // 1000)
    return pd.to_datetime(ms, unit="ms", utc=True)


def _fetch_zip_csv(url: str) -> pd.DataFrame | None:
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0])
    first = raw.split(b"\n", 1)[0]
    has_header = not first[:1].isdigit()
    return pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)


def _day_klines(symbol: str, day: str, cache: Path) -> pd.DataFrame | None:
    """Daily archive, used for the current month before its monthly file exists."""
    path = cache / "klines_daily" / symbol / f"{symbol}-1m-{day}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = _fetch_zip_csv(f"{DAILY}/klines/{symbol}/1m/{symbol}-1m-{day}.zip")
    if df is None:
        return None
    out = _clean_klines(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def _month_klines(symbol: str, month: str, cache: Path) -> pd.DataFrame | None:
    path = cache / "klines" / symbol / f"{symbol}-1m-{month}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = _fetch_zip_csv(f"{BASE}/klines/{symbol}/1m/{symbol}-1m-{month}.zip")
    if df is None:
        days = pd.date_range(month + "-01", periods=pd.Period(month).days_in_month, freq="D")
        parts = [_day_klines(symbol, d.strftime("%Y-%m-%d"), cache) for d in days]
        parts = [x for x in parts if x is not None and len(x)]
        return pd.concat(parts, ignore_index=True) if parts else None
    out = _clean_klines(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def _clean_klines(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = KLINE_COLS[: df.shape[1]]
    return pd.DataFrame({
        "open_time": _to_utc(df["open_time"]),
        "open": df["open"].astype(float),
        "high": df["high"].astype(float),
        "low": df["low"].astype(float),
        "close": df["close"].astype(float),
        "volume": df["volume"].astype(float),
        "quote_volume": df["quote_volume"].astype(float),
    })


def _month_funding(symbol: str, month: str, cache: Path) -> pd.DataFrame | None:
    path = cache / "funding" / symbol / f"{symbol}-fundingRate-{month}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = _fetch_zip_csv(f"{BASE}/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip")
    if df is None:
        return None
    out = pd.DataFrame({
        "time": _to_utc(df["calc_time"]).dt.floor("min"),
        "rate": df["last_funding_rate"].astype(float),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def load_klines(symbol: str, start: str, end: str, cache: Path = DEFAULT_CACHE,
                workers: int = 8) -> pd.DataFrame:
    """1m klines indexed by bar open_time (UTC), on a complete minute grid.

    Missing minutes (exchange outages) are filled with a flat bar at the
    previous close and zero volume; column `filled` marks them.
    """
    months = _months(start, end)
    with ThreadPoolExecutor(workers) as ex:
        parts = list(ex.map(lambda m: _month_klines(symbol, m, cache), months))
    parts = [p for p in parts if p is not None and len(p)]
    if not parts:
        raise ValueError(f"no kline data for {symbol} {start}..{end}")
    df = pd.concat(parts).drop_duplicates("open_time").set_index("open_time").sort_index()
    grid = pd.date_range(df.index[0], df.index[-1], freq="1min", tz="UTC")
    df = df.reindex(grid)
    df["filled"] = df["close"].isna()
    df["close"] = df["close"].ffill()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    df[["volume", "quote_volume"]] = df[["volume", "quote_volume"]].fillna(0.0)
    df.index.name = "open_time"
    return df


def load_funding(symbol: str, start: str, end: str, cache: Path = DEFAULT_CACHE) -> pd.DataFrame:
    """Funding settlements: `time` (UTC, floored to the minute) and `rate`."""
    parts = [_month_funding(symbol, m, cache) for m in _months(start, end)]
    parts = [p for p in parts if p is not None and len(p)]
    if not parts:
        return pd.DataFrame(columns=["time", "rate"])
    return pd.concat(parts).drop_duplicates("time").sort_values("time").reset_index(drop=True)
