"""Deribit DVOL (30-day implied volatility index) history via the public API.

DVOL is Deribit's model-free 30-day implied vol index (annualised, in vol points),
the crypto counterpart of the VIX.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
CACHE = Path(__file__).resolve().parent / "data_cache"


def fetch_dvol(currency: str = "BTC", start: str = "2021-03-01", end: str = "2026-11-18",
               resolution: str = "3600") -> pd.DataFrame:
    path = CACHE / f"dvol_{currency}_{resolution}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    rows, cur_end = [], t1
    while True:
        r = requests.get(URL, params=dict(currency=currency, start_timestamp=t0, end_timestamp=cur_end,
                                          resolution=resolution), timeout=30)
        r.raise_for_status()
        res = r.json()["result"]
        data = res.get("data", [])
        if not data:
            break
        rows.extend(data)
        cont = res.get("continuation")
        if not cont or cont <= t0:
            break
        cur_end = cont
        time.sleep(0.2)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"]).drop_duplicates("ts")
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("time").sort_index()[["open", "high", "low", "close"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df
