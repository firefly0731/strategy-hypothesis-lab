"""Stage A event study (see DESIGN.md).

Pass 1 (`second_grid`): per symbol, a 1-second grid on exchange time: last price, taker buy and
sell notional, and trade count. Pass 2 (`outcomes`): for each break, entry and exit prices from
the raw trades, for every delay and horizon.

Every quantity at grid second i uses only trades with time <= T_i (the end of that second).
Baselines use whole previous days only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from numba import njit

from .fetch_aggtrades import OUT, months_between

DAY_S = 86_400
LOOKBACK_D = 14
LS = (10, 60)
QS = (0.90, 0.95, 0.99, 0.995, 0.999)
DELAYS_MS = (0, 50, 100, 250, 500, 1000)
HORIZONS_S = (10, 30, 60, 300)
COST_BP = 5.0          # default; per symbol: 4 + max(1, tick_bp / 2), see cost_bp()
DISCOVERY = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
HOLDOUT = ("BNBUSDT", "XRPUSDT", "DOGEUSDT")
LARGE_TICK = ("ADAUSDT", "NEARUSDT", "WLDUSDT", "TRUMPUSDT", "FETUSDT")


def cost_bp(tick: float, ref_px: float) -> float:
    return 4.0 + max(1.0, 0.5 * tick / ref_px * 1e4)
# |z| histogram for the rolling quantile: log-spaced bins
EDGES = np.concatenate([[0.0], np.logspace(-4, 3, 2801)])


def trade_path(sym: str, month: str, out=OUT):
    return out / sym / f"{month}.parquet"


def load_trades(sym: str, month: str, cols=("t", "px", "qty", "buyer_maker"), until_ms=None):
    p = trade_path(sym, month)
    filt = [("t", "<", until_ms)] if until_ms is not None else None
    return pq.read_table(p, columns=list(cols), filters=filt).to_pandas()


# ----------------------------------------------------------------------------- pass 1

def second_grid(sym: str, months: list[str]) -> dict:
    """Return arrays on the 1-second grid T_i = start + (i+1)*1000 ms (end of second i)."""
    first = pd.Timestamp(months[0] + "-01", tz="UTC")
    y, m = map(int, months[-1].split("-"))
    last = pd.Timestamp(year=y + (m == 12), month=1 if m == 12 else m + 1, day=1, tz="UTC")
    start_ms = int(first.timestamp() * 1000)
    n = int((last - first).total_seconds())
    px = np.full(n, np.nan)
    buy = np.zeros(n, dtype=np.float32)
    sell = np.zeros(n, dtype=np.float32)
    cnt = np.zeros(n, dtype=np.int32)
    carry = np.nan
    for mo in months:
      for batch in pq.ParquetFile(trade_path(sym, mo)).iter_batches(batch_size=4_000_000):
        df = batch.to_pandas()
        t = df["t"].to_numpy()
        sec = (t - start_ms) // 1000
        ok = (sec >= 0) & (sec < n)
        sec, p = sec[ok], df["px"].to_numpy()[ok]
        notional = (df["px"].to_numpy() * df["qty"].to_numpy())[ok]
        bm = df["buyer_maker"].to_numpy()[ok]
        # last trade in each second (data is time-ordered)
        last_idx = np.flatnonzero(np.r_[sec[1:] != sec[:-1], True])
        px[sec[last_idx]] = p[last_idx]
        sell += np.bincount(sec[bm], notional[bm], minlength=n).astype(np.float32)  # taker sold
        buy += np.bincount(sec[~bm], notional[~bm], minlength=n).astype(np.float32)
        cnt += np.bincount(sec, minlength=n).astype(np.int32)
        del df
    # forward fill: price at T_i is the last trade at or before T_i
    px = pd.Series(px).ffill().to_numpy()
    return {"start_ms": start_ms, "px": px, "buy": buy, "sell": sell, "cnt": cnt}


def _prior_day_mean(day_hour: np.ndarray, lookback: int = LOOKBACK_D) -> np.ndarray:
    """day_hour[d, h] -> mean over days d-lookback..d-1 (NaN until `lookback` days exist)."""
    df = pd.DataFrame(day_hour)
    return df.rolling(lookback, min_periods=lookback).mean().shift(1).to_numpy()


def _per_day_hour(v: np.ndarray, n_days: int) -> np.ndarray:
    a = v[: n_days * DAY_S].reshape(n_days, 24, 3600)
    return np.nanmean(a, axis=2)


def zscores(g: dict, L: int) -> dict:
    """z_t = x_t / s_t with s from previous days only (see DESIGN.md)."""
    px = g["px"]
    n_days = len(px) // DAY_S
    n = n_days * DAY_S
    lp = np.log(px[:n])
    x = np.full(n, np.nan, dtype=np.float32)
    x[L:] = lp[L:] - lp[:-L]
    cs = np.cumsum(np.nan_to_num(np.abs(np.diff(lp, prepend=lp[0]))))
    del lp
    rv = np.full(n, np.nan, dtype=np.float32)
    rv[900:] = cs[900:] - cs[:-900]
    del cs
    base_x = _prior_day_mean(_per_day_hour(np.abs(x), n_days))      # [day, hour]
    base_rv = _prior_day_mean(_per_day_hour(rv, n_days))
    # broadcast [day, hour] baselines over the 3600 seconds of each hour
    scale = (base_x / base_rv).astype(np.float32)[:, :, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        z = x.reshape(n_days, 24, 3600) / (scale * rv.reshape(n_days, 24, 3600))
    del rv
    return {"x": x, "z": z.reshape(-1), "n_days": n_days}


def thresholds(z: np.ndarray, n_days: int, qs=QS) -> np.ndarray:
    """k[day, j]: q_j-quantile of |z| over the previous LOOKBACK_D days (from day histograms)."""
    az = np.abs(z[: n_days * DAY_S]).reshape(n_days, DAY_S)
    hist = np.zeros((n_days, len(EDGES) - 1))
    for d in range(n_days):
        v = az[d][np.isfinite(az[d])]
        hist[d] = np.histogram(np.clip(v, 0, EDGES[-1] * 0.999), bins=EDGES)[0]
    k = np.full((n_days, len(qs)), np.nan)
    for d in range(LOOKBACK_D, n_days):
        h = hist[d - LOOKBACK_D: d].sum(axis=0)
        if h.sum() < 0.5 * LOOKBACK_D * DAY_S:
            continue
        c = np.cumsum(h) / h.sum()
        for j, q in enumerate(qs):
            k[d, j] = EDGES[1:][np.searchsorted(c, q)]
    return k


@njit(cache=True)
def _breaks(z, x, k_sec, L):
    out = []
    armed = True
    last = -10 ** 9
    for i in range(len(z)):
        zi, ki = z[i], k_sec[i]
        if not (np.isfinite(zi) and np.isfinite(ki)):
            continue
        a = abs(zi)
        if not armed:
            if a <= ki and i - last >= L:
                armed = True
            continue
        if a > ki:
            out.append(i)
            armed = False
            last = i
    return np.array(out, dtype=np.int64)


def breaks(zs: dict, k: np.ndarray, j: int, L: int) -> pd.DataFrame:
    n = zs["n_days"] * DAY_S
    k_sec = np.repeat(k[:, j], DAY_S)[:n]
    idx = _breaks(zs["z"][:n], zs["x"][:n], k_sec, L)
    return pd.DataFrame({"i": idx, "sign": np.sign(zs["x"][idx]).astype(int),
                         "absz": np.abs(zs["z"][idx]), "k": k_sec[idx]})


# ----------------------------------------------------------------------------- pass 2

def _load_tp(sym: str, month: str, base_ms: int, until_ms=None):
    """Trade times as uint32 ms after `base_ms` and prices as float32 (about 0.001 bp precision).
    Read row group by row group to keep peak memory low."""
    pf = pq.ParquetFile(trade_path(sym, month))
    ts, ps = [], []
    for rg in range(pf.num_row_groups):
        tb = pf.read_row_group(rg, columns=["t", "px"])
        t = tb.column("t").to_numpy()
        if until_ms is not None:
            keep = t < until_ms
            if not keep.any():
                break
            t, p = t[keep], tb.column("px").to_numpy()[keep]
        else:
            p = tb.column("px").to_numpy()
        ts.append((t - base_ms).astype(np.uint32))
        ps.append(p.astype(np.float32))
        del tb, t, p
    return np.concatenate(ts), np.concatenate(ps)


def outcomes(sym: str, months: list[str], start_ms: int, ev: pd.DataFrame,
             delays=DELAYS_MS, horizons=HORIZONS_S) -> pd.DataFrame:
    """Continuation g[bp] for each event, delay and horizon, from raw trades.

    Detection time T = start + (i+1)*1000 ms. Entry = first trade at or after T + d.
    Exit = last trade at or before T + d + h.
    """
    T = start_ms + (ev["i"].to_numpy() + 1) * 1000
    res = {f"g_d{d}_h{h}": np.full(len(ev), np.nan) for d in delays for h in horizons}
    pad = (max(delays) + max(horizons) * 1000) + 1000
    for mi, mo in enumerate(months):
        lo = int(pd.Timestamp(mo + "-01", tz="UTC").timestamp() * 1000)
        nxt = months[mi + 1] if mi + 1 < len(months) else None
        sel = np.flatnonzero((T >= lo) & ((T < int(pd.Timestamp(nxt + "-01", tz="UTC").timestamp() * 1000))
                                          if nxt else True))
        if not len(sel):
            continue
        t, p = _load_tp(sym, mo, lo)
        if nxt:
            hi = int(pd.Timestamp(nxt + "-01", tz="UTC").timestamp() * 1000) + pad
            t2, p2 = _load_tp(sym, nxt, lo, until_ms=hi)
            t, p = np.concatenate([t, t2]), np.concatenate([p, p2])
            del t2, p2
        T_rel = (T[sel] - lo).astype(np.int64)
        sg = ev["sign"].to_numpy()[sel]
        for d in delays:
            je = np.searchsorted(t, T_rel + d, side="left")
            ok_e = je < len(t)
            pe = np.where(ok_e, p[np.minimum(je, len(t) - 1)], np.nan)
            for h in horizons:
                jx = np.searchsorted(t, T_rel + d + h * 1000, side="right") - 1
                ok = ok_e & (jx >= je) & (jx < len(t))
                px_x = np.where(ok, p[np.clip(jx, 0, len(t) - 1)], np.nan)
                res[f"g_d{d}_h{h}"][sel] = sg * np.log(px_x.astype(np.float64) / pe) * 1e4
        del t, p
    return pd.concat([ev.reset_index(drop=True), pd.DataFrame(res)], axis=1)


def random_controls(n_days: int, ev: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Same hour-of-day mix as `ev`, random day (after warm-up) and random direction."""
    hour = (ev["i"].to_numpy() % DAY_S) // 3600
    day = rng.integers(2 * LOOKBACK_D, n_days, len(ev))
    i = day * DAY_S + hour * 3600 + rng.integers(0, 3600, len(ev))
    return pd.DataFrame({"i": i, "sign": rng.choice([-1, 1], len(ev)),
                         "absz": np.nan, "k": np.nan})
