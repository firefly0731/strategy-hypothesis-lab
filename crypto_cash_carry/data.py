"""Binance spot + USDⓈ-M perp data on one hourly grid, plus FRED DTB3 (DESIGN.md §1).

The archive loaders and cache are shared with crypto_dirty_carry (same parquet layout), so perp
klines/funding already downloaded there are reused.
"""
from __future__ import annotations

import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from crypto_dirty_carry.data import (ARCHIVE_S3, DEFAULT_CACHE, FAPI, _funding, _funding_rest, _klines,
                                     _session)

from .engine import Market

ARCHIVE_START = pd.Period("2020-01", freq="M")      # first month of the USDⓈ-M kline/funding archive
MMR = {"BTCUSDT": 0.004, "ETHUSDT": 0.005}          # tier-1 maintenance margin; others DEFAULT_MMR
DEFAULT_MMR = 0.01
_MULT = re.compile(r"^(1000000|100000|10000|1000|1M)(.+)$")


def perp_to_spot(perp: str) -> tuple[str, float]:
    """1000PEPEUSDT → (PEPEUSDT, 1000); 1MBABYDOGEUSDT → (BABYDOGEUSDT, 1e6); BTCUSDT → (BTCUSDT, 1)."""
    m = _MULT.match(perp)
    if not m:
        return perp, 1.0
    k = 1e6 if m.group(1) == "1M" else float(m.group(1))
    return m.group(2), k


def spot_archive_symbols(quote: str = "USDT", cache: Path = DEFAULT_CACHE, refresh: bool = False) -> list[str]:
    path = cache / "archive_symbols_spot.json"
    if path.exists() and not refresh:
        syms = json.loads(path.read_text(encoding="utf-8"))
    else:
        syms, marker, prefix = [], "", "data/spot/monthly/klines/"
        while True:
            r = requests.get(ARCHIVE_S3, params={"delimiter": "/", "prefix": prefix, "marker": marker}, timeout=60)
            r.raise_for_status()
            page = re.findall(rf"<Prefix>{prefix}([^<]+)/</Prefix>", r.text)
            syms += page
            if "<IsTruncated>true" not in r.text or not page:
                break
            marker = prefix + page[-1] + "/"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(syms), encoding="utf-8")
    return sorted(s for s in syms if s.endswith(quote))


def _rest_perp_klines(symbol: str, month: str, cache: Path) -> pd.DataFrame | None:
    """fapi/v1/klines for one month that predates the archive (cached like an archive month)."""
    path = cache / "klines_1h_rest" / symbol / f"{month}.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        return df if len(df) else None
    p = pd.Period(month, freq="M")
    t0 = int(p.start_time.tz_localize("UTC").value // 10**6)
    t1 = int(p.end_time.tz_localize("UTC").value // 10**6)
    rows = []
    while t0 <= t1:
        r = _session().get(f"{FAPI}/fapi/v1/klines", timeout=30,
                           params=dict(symbol=symbol, interval="1h", startTime=t0, endTime=t1, limit=1500))
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows += batch
        t0 = batch[-1][0] + 3_600_000
        if len(batch) < 1500:
            break
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]
    df = pd.DataFrame([x[:8] for x in rows], columns=cols)
    out = pd.DataFrame({"open_time": pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True),
                        "high": df["high"].astype(float), "close": df["close"].astype(float),
                        "quote_volume": df["quote_volume"].astype(float)})
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out if len(out) else None


def load_klines(symbol: str, market: str, start: str, end: str, cache: Path = DEFAULT_CACHE) -> pd.DataFrame | None:
    """open_time, high, close, quote_volume (hourly). Perp months before the archive come from REST."""
    k = _klines(symbol, "1h", start, end, cache, market=market)
    parts = [] if k is None else [k[["open_time", "high", "close", "quote_volume"]]]
    if market == "um" and pd.Period(start, freq="M") < ARCHIVE_START:
        for month in pd.period_range(start, min(pd.Period(end, freq="M"), ARCHIVE_START - 1), freq="M"):
            r = _rest_perp_klines(symbol, month.strftime("%Y-%m"), cache)
            if r is not None:
                parts.append(r)
    if not parts:
        return None
    return (pd.concat(parts, ignore_index=True).drop_duplicates("open_time").sort_values("open_time")
            .reset_index(drop=True))


def load_funding(symbol: str, start: str, end: str, traded_until: pd.Timestamp,
                 cache: Path = DEFAULT_CACHE) -> pd.DataFrame:
    f = _funding(symbol, max(start, str(ARCHIVE_START)), end, cache, traded_until=traded_until)
    if pd.Period(start, freq="M") < ARCHIVE_START:
        head = _funding_rest(symbol, pd.Period(start, freq="M").start_time.tz_localize("UTC"),
                             ARCHIVE_START.start_time.tz_localize("UTC") - pd.Timedelta(minutes=1))
        f = pd.concat([head, f], ignore_index=True).drop_duplicates("time").sort_values("time")
    return f.reset_index(drop=True)


def funding_to_grid(times: pd.Series, rates: pd.Series, index: pd.DatetimeIndex) -> np.ndarray:
    """Settlement at s → bar (t_{j−1}, t_j], i.e. the first close ≥ s. Settlements outside the grid
    are dropped; two in one bar are summed."""
    out = np.zeros(len(index))
    t = pd.DatetimeIndex(times)
    keep = (t > index[0] - (index[1] - index[0])) & (t <= index[-1])
    j = index.searchsorted(t[keep], side="left")
    assert (j < len(index)).all()
    np.add.at(out, j, np.asarray(rates, float)[keep])
    return out


@dataclass
class Bundle:
    market: Market
    last_high: np.ndarray            # (N, S) perp LAST-price high (wicks; not used for liquidation)
    liq_proxy_bars: np.ndarray       # (S,) bars where the mark high was missing and the spot proxy was used
    spot_qv: np.ndarray
    perp_qv: np.ndarray
    n_settlements: np.ndarray        # (S,) settlements mapped into the grid
    neg_settlements: np.ndarray      # (S,) of which rate < 0
    mult: dict


def build(perps: list[str], start: str, end: str, cache: Path = DEFAULT_CACHE, workers: int = 8,
          spot_listed: set[str] | None = None) -> Bundle:
    """Grid of bar CLOSE times from `start` 00:00 to `end` + 1 day 00:00 (end date inclusive)."""
    idx = pd.date_range(pd.Timestamp(start, tz="UTC") + pd.Timedelta(hours=1),
                        pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1), freq="1h")
    m0, m1 = pd.Timestamp(start).strftime("%Y-%m"), pd.Timestamp(end).strftime("%Y-%m")

    def one(perp):
        spot, k = perp_to_spot(perp)
        if spot_listed is not None and spot not in spot_listed:
            return perp, None
        kp = load_klines(perp, "um", m0, m1, cache)
        if kp is None:
            return perp, None
        ks = load_klines(spot, "spot", m0, m1, cache)
        if ks is None:
            return perp, None
        f = load_funding(perp, m0, m1, traded_until=kp["open_time"].iloc[-1] + pd.Timedelta(hours=1), cache=cache)
        km = _klines(perp, "1h", max(m0, str(ARCHIVE_START)), m1, cache, market="mark")
        return perp, (kp, ks, f, k, km)

    with ThreadPoolExecutor(workers) as ex:
        got = [(p, d) for p, d in ex.map(one, perps) if d is not None]
    if not got:
        raise ValueError("no symbol has both spot and perp data")
    syms = [p for p, _ in got]
    N, S = len(idx), len(syms)
    spot = np.full((N, S), np.nan)
    perp = np.full((N, S), np.nan)
    high = np.full((N, S), np.nan)
    liq = np.full((N, S), np.nan)
    shigh = np.full((N, S), np.nan)
    sqv = np.full((N, S), np.nan, dtype=np.float32)
    pqv = np.full((N, S), np.nan, dtype=np.float32)
    fund = np.zeros((N, S))
    nset = np.zeros(S, int)
    nneg = np.zeros(S, int)
    for j, (p, (kp, ks, f, k, km)) in enumerate(got):
        ip = pd.DatetimeIndex(kp["open_time"]) + pd.Timedelta(hours=1)
        isp = pd.DatetimeIndex(ks["open_time"]) + pd.Timedelta(hours=1)
        perp[:, j] = pd.Series(kp["close"].to_numpy() / k, index=ip).reindex(idx).to_numpy()
        high[:, j] = pd.Series(kp["high"].to_numpy() / k, index=ip).reindex(idx).to_numpy()
        pqv[:, j] = pd.Series(kp["quote_volume"].to_numpy(), index=ip).reindex(idx).to_numpy()
        spot[:, j] = pd.Series(ks["close"].to_numpy(), index=isp).reindex(idx).to_numpy()
        sqv[:, j] = pd.Series(ks["quote_volume"].to_numpy(), index=isp).reindex(idx).to_numpy()
        shigh[:, j] = pd.Series(ks["high"].to_numpy(), index=isp).reindex(idx).to_numpy()
        if km is not None and len(km):
            km = km.drop_duplicates("open_time")
            im = pd.DatetimeIndex(km["open_time"]) + pd.Timedelta(hours=1)
            liq[:, j] = pd.Series(km["high"].to_numpy() / k, index=im).reindex(idx).to_numpy()
        if len(f):
            fund[:, j] = funding_to_grid(f["time"], f["rate"], idx)
            inside = (pd.DatetimeIndex(f["time"]) > idx[0] - pd.Timedelta(hours=1)) & \
                     (pd.DatetimeIndex(f["time"]) <= idx[-1])
            nset[j] = int(inside.sum())
            nneg[j] = int((f["rate"].to_numpy()[inside] < 0).sum())
    # a zero/negative print would break the accounting: treat as missing (logged by the caller)
    for a in (spot, perp, high, liq, shigh):
        a[~(a > 0)] = np.nan
    # mark high missing (pre-2020 or archive gaps): spot high scaled by the bar's perp/spot ratio
    proxy = ~np.isfinite(liq) & np.isfinite(shigh) & np.isfinite(perp) & np.isfinite(spot)
    with np.errstate(invalid="ignore"):
        liq = np.where(proxy, shigh * perp / spot, liq)
    held = np.isfinite(perp) & np.isfinite(spot)
    mmr = np.array([MMR.get(s, DEFAULT_MMR) for s in syms])
    mk = Market(index=idx, symbols=syms, spot=spot, perp=perp, liq_high=liq, funding=fund, mmr=mmr)
    return Bundle(market=mk, last_high=high, liq_proxy_bars=(proxy & held).sum(axis=0), spot_qv=sqv, perp_qv=pqv, n_settlements=nset, neg_settlements=nneg,
                  mult={p: d[3] for p, d in got if d[3] != 1.0})


def dtb3(cache: Path = DEFAULT_CACHE, refresh: bool = False) -> pd.Series:
    """FRED DTB3 (3-month T-bill secondary market rate, % p.a., discount basis), daily, UTC dates.
    Raises if it cannot be fetched: there is no fallback series."""
    path = cache / "fred_DTB3.csv"
    if refresh or not path.exists():
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": "DTB3"}, timeout=60)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    df = pd.read_csv(path)
    date_col = df.columns[0]
    s = pd.to_numeric(df["DTB3"], errors="coerce")
    s.index = pd.DatetimeIndex(pd.to_datetime(df[date_col])).tz_localize("UTC")
    s = s.dropna()
    assert len(s) and (s.index == s.index.normalize()).all()
    return s
