"""Input panel for the dirty carry backtest, its time conventions, and the Binance loader.

Conventions (all timestamps UTC):
* `close` is indexed by BAR CLOSE time t on a regular grid. close[t] is the last price of the bar
  (t - Δ, t] and is known at t. The bar return r[t] = close[t] / close[t - Δ] - 1 is known at t.
  Missing bars stay NaN (before listing, after delisting, outages).
* `factors[t]` is the factor's simple return over the same bar (t - Δ, t]. Same index as `close`.
* `quote_volume[t]` (optional) is traded quote volume within the bar.
* `funding` is long format with columns time, symbol, rate. `time` is the settlement time s and
  `rate` the settled rate, known at s.
  Sign convention (Binance USDⓈ-M, and most perp venues): rate > 0 → longs pay shorts.
  The cash flow to the holder is  -notional(s) × rate, with notional signed (+ long, - short).
  So a short receives positive funding and a long receives negative funding.
* A settlement at s belongs to bar j with t_{j-1} < s ≤ t_j. It applies to the position held during
  that bar, i.e. the position after the trades executed at close t_{j-1}. Trades executed at close
  t_j, even when t_j == s, happen after the settlement and neither pay nor receive it.

Look-ahead safety: every decision receives `MarketData.snapshot(t)`, a view that physically
contains only rows with time ≤ t.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import requests

YEAR = pd.Timedelta(days=365)
FUNDING_COLUMNS = ("time", "symbol", "rate")
DEFAULT_CACHE = Path(__file__).resolve().parent / "data_cache"


def _check_index(idx, name: str) -> None:
    if not isinstance(idx, pd.DatetimeIndex):
        raise TypeError(f"{name}: index must be a DatetimeIndex")
    if idx.tz is None or str(idx.tz) != "UTC":
        raise ValueError(f"{name}: index must be tz-aware UTC")
    if not idx.is_monotonic_increasing or idx.has_duplicates:
        raise ValueError(f"{name}: index must be strictly increasing")


@dataclass(frozen=True)
class Snapshot:
    """Data visible at decision time t: every row has time ≤ t."""
    t: pd.Timestamp
    close: pd.DataFrame
    quote_volume: pd.DataFrame | None
    factors: pd.DataFrame
    funding: pd.DataFrame
    bar: pd.Timedelta

    @property
    def bars_per_year(self) -> float:
        return YEAR / self.bar


@dataclass(frozen=True)
class MarketData:
    close: pd.DataFrame
    funding: pd.DataFrame
    factors: pd.DataFrame
    quote_volume: pd.DataFrame | None = None

    def __post_init__(self):
        idx = self.close.index
        _check_index(idx, "close")
        if len(idx) < 3:
            raise ValueError("close needs at least 3 bars")
        steps = np.diff(idx.as_unit("ns").asi8)
        if (steps != steps[0]).any():
            raise ValueError("close index must be a regular grid (reindex; leave gaps as NaN)")
        if self.close.columns.has_duplicates:
            raise ValueError("close has duplicate symbols")
        vals = self.close.to_numpy(dtype=float)
        if (vals[np.isfinite(vals)] <= 0).any():
            raise ValueError("close prices must be positive")
        if not self.factors.index.equals(idx):
            raise ValueError("factors must share the close index")
        if self.quote_volume is not None and not (
                self.quote_volume.index.equals(idx) and self.quote_volume.columns.equals(self.close.columns)):
            raise ValueError("quote_volume must have the same index and columns as close")
        object.__setattr__(self, "funding", self._normalise_funding(self.funding))

    def _normalise_funding(self, f: pd.DataFrame) -> pd.DataFrame:
        missing = set(FUNDING_COLUMNS) - set(f.columns)
        if missing:
            raise ValueError(f"funding is missing columns {sorted(missing)}")
        if len(f) == 0:
            return pd.DataFrame({"time": pd.DatetimeIndex([], tz="UTC"),
                                 "symbol": pd.Series([], dtype=object),
                                 "rate": pd.Series([], dtype=float)})
        times = pd.DatetimeIndex(f["time"])
        if times.tz is None:
            raise ValueError("funding.time must be tz-aware (UTC)")
        unknown = set(f["symbol"]) - set(self.close.columns)
        if unknown:
            raise ValueError(f"funding has symbols not in close: {sorted(unknown)[:5]}")
        rate = f["rate"].to_numpy(dtype=float)
        if not np.isfinite(rate).all():
            raise ValueError("funding.rate must be finite")
        out = pd.DataFrame({"time": times.tz_convert("UTC").as_unit("ns"),
                            "symbol": f["symbol"].to_numpy(), "rate": rate})
        if out.duplicated(["time", "symbol"]).any():
            raise ValueError("funding has duplicate (time, symbol) rows")
        return out.sort_values(["time", "symbol"], kind="stable").reset_index(drop=True)

    @property
    def symbols(self) -> pd.Index:
        return self.close.columns

    @property
    def bar(self) -> pd.Timedelta:
        return self.close.index[1] - self.close.index[0]

    @property
    def bars_per_year(self) -> float:
        return YEAR / self.bar

    @cached_property
    def _funding_times(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.funding["time"])

    def snapshot(self, t, lookback: pd.Timedelta, funding_history: pd.Timedelta) -> Snapshot:
        """Rows with time in (t - lookback - 1 bar, t] for prices and (t - funding_history, t]
        for funding. Nothing after t is included."""
        t = pd.Timestamp(t)
        idx = self.close.index
        j = idx.searchsorted(t, side="right")
        if j == 0:
            raise ValueError(f"no bars at or before {t}")
        i0 = max(0, idx.searchsorted(t - lookback, side="left") - 1)
        rows = slice(i0, j)
        ft = self._funding_times
        lo = ft.searchsorted(t - funding_history, side="right")
        hi = ft.searchsorted(t, side="right")
        return Snapshot(
            t=t,
            close=self.close.iloc[rows],
            quote_volume=None if self.quote_volume is None else self.quote_volume.iloc[rows],
            factors=self.factors.iloc[rows],
            funding=self.funding.iloc[lo:hi],
            bar=self.bar,
        )


def factor_from_close(close: pd.DataFrame, symbol: str) -> pd.Series:
    """Simple return of one traded symbol over each bar (known at the bar close)."""
    return close[symbol].pct_change(fill_method=None)


def equal_weight_factor(close: pd.DataFrame, exclude: Iterable[str] = ()) -> pd.Series:
    """Equal-weight return of all names with a return in the bar (e.g. an alt basket factor).
    Uses only bar-t returns, so it is known at t."""
    r = close.drop(columns=list(exclude), errors="ignore").pct_change(fill_method=None)
    return r.mean(axis=1, skipna=True)


# ---------------------------------------------------------------------------------------------
# Binance USDⓈ-M loader (data.binance.vision archives + public REST for the latest settlements)
# ---------------------------------------------------------------------------------------------
FAPI = "https://fapi.binance.com"


def binance_universe(quote: str = "USDC", cache: Path = DEFAULT_CACHE, refresh: bool = False) -> pd.DataFrame:
    """Perpetuals with the given margin/quote asset from /fapi/v1/exchangeInfo.

    The endpoint lists only symbols that still exist (TRADING or SETTLING), so contracts that were
    delisted earlier are missing: a survivorship bias that callers should report. The response
    is cached under data_cache/ with its download date.
    """
    path = cache / f"exchangeInfo_{quote}.json"
    if path.exists() and not refresh:
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=30)
        r.raise_for_status()
        rows = [dict(symbol=s["symbol"], status=s["status"], onboard_ms=s["onboardDate"])
                for s in r.json()["symbols"]
                if s.get("quoteAsset") == quote and s.get("contractType") == "PERPETUAL"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
    df = pd.DataFrame(rows)
    df["onboard"] = pd.to_datetime(df["onboard_ms"], unit="ms", utc=True)
    return df.drop(columns="onboard_ms").sort_values("onboard").reset_index(drop=True)


ARCHIVE_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
INDEX_CONTRACTS = {"DEFIUSDT", "BTCDOMUSDT", "FOOTBALLUSDT", "BLUEBIRDUSDT", "ALLUSDT"}


def binance_archive_symbols(quote: str = "USDT", cache: Path = DEFAULT_CACHE, refresh: bool = False) -> list[str]:
    """Every USDⓈ-M symbol that ever had a monthly kline archive, delisted ones included.
    Delivery contracts (names with '_') are dropped. This is the point-in-time universe source:
    which of these traded at a given time is decided by their price data, not by today's listing."""
    import re

    path = cache / "archive_symbols_um.json"
    if path.exists() and not refresh:
        syms = json.loads(path.read_text(encoding="utf-8"))
    else:
        syms, marker, prefix = [], "", "data/futures/um/monthly/klines/"
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
    return sorted(s for s in syms if s.endswith(quote) and "_" not in s)


def non_coin_symbols(cache: Path = DEFAULT_CACHE, refresh: bool = False) -> set[str]:
    """Symbols that are not single-coin perpetuals: TradFi (equities, commodities, FX), indices and
    pre-market contracts from today's exchangeInfo, plus known delisted index contracts."""
    path = cache / "non_coin_symbols.json"
    if path.exists() and not refresh:
        return set(json.loads(path.read_text(encoding="utf-8")))
    r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=30)
    r.raise_for_status()
    out = {s["symbol"] for s in r.json()["symbols"]
           if s.get("underlyingType") != "COIN" or s.get("contractType") != "PERPETUAL"} | INDEX_CONTRACTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(out)), encoding="utf-8")
    return out


def _fetch(url: str, tries: int = 4):
    """data.binance.vision zip → DataFrame (None on 404), retrying dropped connections."""
    import time

    from crypto_intraday_momentum.data import _fetch_zip_csv

    for i in range(tries):
        try:
            return _fetch_zip_csv(url)
        except requests.exceptions.ConnectionError:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def _klines(symbol: str, interval: str, start: str, end: str, cache: Path) -> pd.DataFrame | None:
    from crypto_intraday_momentum.data import BASE, DAILY, _clean_klines

    parts = []
    now = pd.Timestamp.now(tz="UTC")
    recent = pd.Period(now.tz_localize(None), freq="M") - 1   # monthly file may not be published yet
    for month in pd.period_range(start, end, freq="M").strftime("%Y-%m"):
        path = cache / f"klines_{interval}" / symbol / f"{month}.parquet"
        if path.exists():
            parts.append(pd.read_parquet(path))
            continue
        df = _fetch(f"{BASE}/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip")
        if df is not None:
            out = _clean_klines(df)
            path.parent.mkdir(parents=True, exist_ok=True)
            out.to_parquet(path, index=False)      # complete months only are cached
            parts.append(out)
            continue
        if pd.Period(month, freq="M") < recent:
            continue                                 # older month missing = not listed yet
        days = pd.date_range(month + "-01", periods=pd.Period(month).days_in_month, freq="D")
        days = days[days < now.tz_localize(None).normalize()]
        for d in days.strftime("%Y-%m-%d"):         # current month: daily archives, not cached
            dd = _fetch(f"{DAILY}/klines/{symbol}/{interval}/{symbol}-{interval}-{d}.zip")
            if dd is not None:
                parts.append(_clean_klines(dd))
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else None


def _funding_rest(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows, t0 = [], int(start.value // 10**6)
    t_end = int(end.value // 10**6)
    while t0 < t_end:
        r = requests.get(f"{FAPI}/fapi/v1/fundingRate", timeout=30,
                         params=dict(symbol=symbol, startTime=t0, endTime=t_end, limit=1000))
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows += batch
        t0 = batch[-1]["fundingTime"] + 1
        if len(batch) < 1000:
            break
    if not rows:
        return pd.DataFrame(columns=["time", "rate"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({"time": pd.to_datetime(df["fundingTime"], unit="ms", utc=True).dt.floor("min"),
                         "rate": df["fundingRate"].astype(float)})


def _funding(symbol: str, start: str, end: str, cache: Path,
             traded_until: pd.Timestamp | None = None) -> pd.DataFrame:
    """Monthly archive (data.binance.vision); months not yet archived come from the REST API,
    but only while the symbol still has price data (no REST calls for delisted contracts)."""
    from crypto_intraday_momentum.data import load_funding

    arch = load_funding(symbol, start, end, cache=cache)
    last = pd.Period(end, freq="M").end_time.tz_localize("UTC")
    if traded_until is not None:
        last = min(last, traded_until)
    first = pd.Period(start, freq="M").start_time.tz_localize("UTC")
    tail_from = (pd.Timestamp(arch["time"].max()) + pd.Timedelta(minutes=1)) if len(arch) else first
    if tail_from < min(last, pd.Timestamp.now(tz="UTC")) - pd.Timedelta(hours=8):
        arch = pd.concat([arch, _funding_rest(symbol, tail_from, last)], ignore_index=True)
    return arch.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def from_binance(symbols: Iterable[str], start: str, end: str, bar: str = "1h",
                 factor_map: Mapping[str, str] | None = None, cache: Path = DEFAULT_CACHE,
                 workers: int = 8, funding_min_qv: float | None = None) -> MarketData:
    """Build MarketData from Binance USDⓈ-M archives.

    `bar` must be a kline interval Binance publishes ("1h", "4h", "8h", "1d", ...).
    Kline open_time T is converted to the bar close time T + bar. `factor_map` maps a factor name to
    the traded symbol whose bar return is the factor (default {"BTC": first BTC symbol}).
    funding_min_qv: download optimisation for large universes. Funding is skipped for symbols whose
    30-day median bar quote volume never reaches this value. Those names can never pass a liquidity
    filter at the same threshold, so results are unchanged; they simply get no carry signal.
    """
    symbols = list(symbols)
    step = pd.Timedelta(bar)

    def one(sym):
        k = _klines(sym, bar, start, end, cache)
        if k is None:
            return sym, None, None
        k = k.drop_duplicates("open_time").sort_values("open_time")
        idx = pd.DatetimeIndex(k["open_time"]) + step
        if funding_min_qv is not None:
            med = pd.Series(k["quote_volume"].to_numpy(), index=idx).rolling("30D").median()
            if not (med >= funding_min_qv).any():
                return sym, pd.DataFrame({"close": k["close"].to_numpy(), "qv": k["quote_volume"].to_numpy()},
                                         index=idx), None
        f = _funding(sym, start, end, cache, traded_until=idx[-1])
        return sym, pd.DataFrame({"close": k["close"].to_numpy(), "qv": k["quote_volume"].to_numpy()},
                                 index=idx), f

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, symbols))
    kl = {s: k for s, k, _ in res if k is not None}
    if not kl:
        raise ValueError("no kline data for any symbol")
    lo = min(k.index[0] for k in kl.values())
    hi = max(k.index[-1] for k in kl.values())
    grid = pd.date_range(lo, hi, freq=step, tz="UTC")
    close = pd.DataFrame({s: k["close"].reindex(grid) for s, k in kl.items()})
    qv = pd.DataFrame({s: k["qv"].reindex(grid) for s, k in kl.items()})
    # archive gaps stay NaN: the simulator holds positions through them, and the eligibility
    # filters (min_obs_frac) exclude names with too many gaps from new decisions
    fund = []
    for s, k, f in res:
        if k is None or f is None or not len(f):
            continue
        f = f[(f["time"] > grid[0]) & (f["time"] <= grid[-1])]
        fund.append(pd.DataFrame({"time": f["time"], "symbol": s, "rate": f["rate"]}))
    funding = pd.concat(fund, ignore_index=True) if fund else pd.DataFrame(columns=list(FUNDING_COLUMNS))
    if factor_map is None:
        btc = [s for s in close.columns if s.startswith("BTC")]
        factor_map = {"BTC": btc[0]} if btc else {}
    factors = pd.DataFrame({name: factor_from_close(close, sym) for name, sym in factor_map.items()},
                           index=grid)
    return MarketData(close=close, funding=funding, factors=factors, quote_volume=qv)
