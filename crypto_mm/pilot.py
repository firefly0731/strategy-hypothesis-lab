"""Pilot: Binance USDC-M vs USDT-M perp books (same underlying, same exchange clock).

Questions
  Q1 book state: spread (ticks / bp), share of time at 1 tick, top-of-book size, quote update rate
  Q2 incumbent MM speed: after the USDT mid moves, how fast does the USDC book move?
  Q3 lead-lag: cross-correlation of mid returns on 10 ms and 50 ms grids (two estimators)
  Q4 maker markout on USDC trades vs the USDT price (fair value), 1 s / 10 s / 60 s

Exchange timestamps (transaction_time, ms) are used throughout, so both books share one clock.

    python -m crypto_mm.pilot --book-date 2024-03-20 --trade-date 2026-11-10 --sym BTC
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent / "data_cache"


def _read(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f)


def load_book(sym: str, date: str) -> pd.DataFrame:
    df = _read(CACHE / f"{sym}-bookTicker-{date}.zip")
    df = df.sort_values(["transaction_time", "update_id"])
    df["t"] = df["transaction_time"].astype("int64")
    df["mid"] = (df["best_bid_price"] + df["best_ask_price"]) / 2
    return df[["t", "best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty", "mid"]]


def book_stats(b: pd.DataFrame, tick: float) -> dict:
    dt = np.diff(b["t"].to_numpy(), append=b["t"].iloc[-1]).astype(float)      # time-weighted
    spr = (b["best_ask_price"] - b["best_bid_price"]).to_numpy()
    ticks = np.round(spr / tick)
    bps = spr / b["mid"].to_numpy() * 1e4
    w = dt / dt.sum()
    top_usd = ((b["best_bid_qty"] + b["best_ask_qty"]) / 2 * b["mid"]).to_numpy()
    secs = (b["t"].iloc[-1] - b["t"].iloc[0]) / 1000
    mid_chg = (b["mid"].diff() != 0).sum()
    return {"updates_per_s": len(b) / secs, "mid_changes_per_s": mid_chg / secs,
            "spread_ticks_tw_mean": float((ticks * w).sum()), "share_1tick": float(w[ticks <= 1].sum()),
            "spread_bp_tw_mean": float((bps * w).sum()), "top_size_usd_median": float(np.median(top_usd))}


def grid_returns(b: pd.DataFrame, step_ms: int, t0: int, t1: int) -> np.ndarray:
    g = np.arange(t0, t1, step_ms)
    idx = np.searchsorted(b["t"].to_numpy(), g, side="right") - 1          # last quote at or before g
    m = b["mid"].to_numpy()[np.clip(idx, 0, None)]
    m[idx < 0] = np.nan
    return np.diff(np.log(m))


def xcorr(x: np.ndarray, y: np.ndarray, lags: range) -> pd.Series:
    """corr(x_t, y_{t+l}): positive l with a high value means x leads y."""
    out = {}
    for l in lags:
        a, b = (x[:-l], y[l:]) if l > 0 else ((x[-l:], y[:l]) if l < 0 else (x, y))
        ok = np.isfinite(a) & np.isfinite(b)
        out[l] = np.corrcoef(a[ok], b[ok])[0, 1]
    return pd.Series(out)


def reaction_times(lead: pd.DataFrame, lag: pd.DataFrame, k_bp: float, horizon_ms: int = 2000):
    """After the lead mid jumps by >= k_bp within one update, time until the lag book's mid
    moves in the same direction (and until any lag-book update)."""
    lm, lt = lead["mid"].to_numpy(), lead["t"].to_numpy()
    r = np.diff(np.log(lm)) * 1e4
    ev = np.flatnonzero(np.abs(r) >= k_bp) + 1
    gm, gt = lag["mid"].to_numpy(), lag["t"].to_numpy()
    rt_same, rt_any = [], []
    for e in ev:
        t = lt[e]
        j = np.searchsorted(gt, t, side="right")                     # first lag update strictly after t
        if j >= len(gt):
            break
        base = gm[j - 1] if j > 0 else np.nan
        rt_any.append(gt[j] - t)
        sgn = np.sign(r[e - 1])
        k = j
        while k < len(gt) and gt[k] - t <= horizon_ms:
            if np.sign(gm[k] - base) == sgn:
                rt_same.append(gt[k] - t)
                break
            k += 1
        else:
            rt_same.append(np.inf)
    return np.array(rt_same, float), np.array(rt_any, float), len(ev)


def trade_markouts(sym_lag: str, sym_lead: str, date: str, horizons=(1000, 10000, 60000)):
    a = _read(CACHE / f"{sym_lag}-trades-{date}.zip")
    f = _read(CACHE / f"{sym_lead}-trades-{date}.zip")
    f = f.sort_values("time")
    ft, fp = f["time"].to_numpy(), f["price"].to_numpy()
    # basis between the two quote currencies: rolling 10-min median ratio of last prices (causal)
    a = a.sort_values("time")
    at, ap = a["time"].to_numpy(), a["price"].to_numpy()
    j0 = np.searchsorted(ft, at, side="right") - 1
    ok = j0 >= 0
    ratio = pd.Series(np.where(ok, ap / fp[np.clip(j0, 0, None)], np.nan), index=pd.to_datetime(at, unit="ms"))
    basis = ratio.rolling("10min").median().shift(1).to_numpy()
    side_maker = np.where(a["is_buyer_maker"].to_numpy(), 1.0, -1.0)    # buyer is maker -> maker bought
    out = {"n_trades": len(a), "median_trade_usd": float(np.median(a["quote_qty"])),
           "p90_trade_usd": float(np.quantile(a["quote_qty"], 0.9))}
    for h in horizons:
        j = np.searchsorted(ft, at + h, side="right") - 1
        fv = fp[np.clip(j, 0, None)] * basis
        mo = side_maker * (fv / ap - 1) * 1e4
        okk = np.isfinite(mo)
        w = a["quote_qty"].to_numpy()[okk]
        out[f"markout_{h//1000}s_bp_mean"] = float(mo[okk].mean())
        out[f"markout_{h//1000}s_bp_volw"] = float(np.average(mo[okk], weights=w))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="BTC")
    ap.add_argument("--book-date", default="2024-03-20")
    ap.add_argument("--trade-date", default="2026-11-10")
    ap.add_argument("--tick", type=float, default=None, help="default: inferred from prices")
    a = ap.parse_args(argv)
    usdc, usdt = f"{a.sym}USDC", f"{a.sym}USDT"
    bc, bt = load_book(usdc, a.book_date), load_book(usdt, a.book_date)
    if a.tick is None:
        px = np.unique(np.concatenate([bc.best_bid_price.to_numpy(), bc.best_ask_price.to_numpy()]))
        d = np.diff(px)
        a.tick = float(np.round(d[d > 0].min(), 10))
        print(f"inferred tick = {a.tick}")
    pd.set_option("display.width", 200)
    print(f"### Q1 book state ({a.book_date})")
    print(pd.DataFrame({usdc: book_stats(bc, a.tick), usdt: book_stats(bt, a.tick)}).round(4).to_string())
    t0, t1 = max(bc.t.iloc[0], bt.t.iloc[0]), min(bc.t.iloc[-1], bt.t.iloc[-1])
    print("\n### Q3 lead-lag: corr(USDT ret_t, USDC ret_{t+lag})  (positive lag = USDT leads)")
    for step in (10, 50):
        x, y = grid_returns(bt, step, t0, t1), grid_returns(bc, step, t0, t1)
        lags = range(-10, 11) if step == 10 else range(-6, 7)
        c = xcorr(x, y, lags)
        c.index = [f"{l*step}ms" for l in c.index]
        print(f"grid {step}ms:", c.round(3).to_dict())
    print("\n### Q2 reaction of the USDC book to USDT mid jumps")
    for k in (0.5, 1.0, 2.0):
        same, anyu, n = reaction_times(bt, bc, k)
        fin = same[np.isfinite(same)]
        print(f"USDT jump >= {k} bp: events={n}  USDC follows same dir within 2s: {len(fin)/max(len(same),1):.1%}  "
              f"latency ms p10/p50/p90 = {np.percentile(fin,10) if len(fin) else np.nan:.0f}/"
              f"{np.percentile(fin,50) if len(fin) else np.nan:.0f}/{np.percentile(fin,90) if len(fin) else np.nan:.0f}  "
              f"| first USDC update after event p50 = {np.median(anyu):.0f} ms")
        same2, _, n2 = reaction_times(bc, bt, k)
        fin2 = same2[np.isfinite(same2)]
        print(f"   reverse (USDC jump -> USDT): events={n2}  p50 = {np.median(fin2) if len(fin2) else np.nan:.0f} ms")
    print(f"\n### Q4 maker markouts on {usdc} trades vs {usdt} price ({a.trade_date})")
    print(pd.Series(trade_markouts(usdc, usdt, a.trade_date)).round(4).to_string())


if __name__ == "__main__":
    main()
