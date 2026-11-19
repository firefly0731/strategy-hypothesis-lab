"""Sanity and fill-assumption checks for the market-neutral grid.

(a) Zero-expectation check on a driftless random walk (no fees): a grid with a stop is a
    martingale strategy, so gross P&L should be ~0 with 'touch' fills and slightly negative
    with 'through' fills (trade-through + no intrabar refill are conservative).
(b) Same real-data runs as run_neutral for the primary and the selected combo with the
    optimistic 'touch' fill rule, to bound how much the fill assumption matters.

    python3 -m crypto_grid.run_sensitivity
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .data import load_funding_local, load_klines_local, ohlc_arrays
from .metrics import day_end_bars, sharpe, tstat
from .neutral import daily_pnl, run_neutral
from .run_neutral import DISC, END, HOLD, START

OUT = Path(__file__).parent / "results" / "sensitivity"


def random_walk_bars(n_bars: int, sigma_1m: float, sub: int = 10, seed: int = 0, martingale: bool = True):
    """Geometric random walk sampled `sub` times per bar. martingale=True subtracts s^2/2 from
    every log step so that the PRICE (not the log price) is a martingale."""
    rng = np.random.default_rng(seed)
    s_ = sigma_1m / np.sqrt(sub)
    steps = rng.normal(-0.5 * s_ ** 2 if martingale else 0.0, s_, size=(n_bars, sub))
    logp = np.cumsum(steps.ravel()).reshape(n_bars, sub) + np.log(100.0)
    close = np.exp(logp[:, -1])
    open_ = np.r_[100.0, close[:-1]]
    path_hi = np.exp(logp.max(axis=1))
    path_lo = np.exp(logp.min(axis=1))
    return open_, np.maximum(path_hi, open_), np.minimum(path_lo, open_), close


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    L = []
    n = 1440 * 1000
    last = np.arange(1439, n, 1440)
    rows = []
    for mart in (True, False):
        for seed in (0, 1, 2):
            o, hi, lo, cl = random_walk_bars(n, 0.0008, seed=seed, martingale=mart)
            for k in (0.005, 0.01, 0.02):
                log = run_neutral(o, hi, lo, cl, k, 6, maker=0.0, taker=0.0, slip=0.0)
                d = daily_pnl(log, cl, last)["gross"]
                rows.append(dict(price="martingale" if mart else "zero log-drift", seed=seed, k=k, h=6,
                                 gross_bp_day=d.mean() * 1e4, t=tstat(d), fills_day=log.n_fills / 1000))
    t = pd.DataFrame(rows)
    L.append("(a) random walk, sigma 0.08%/min, 1000 days x 3 seeds, no fees, 'through' fills\n"
             + t.round(3).to_string(index=False))
    L.append("pooled over seeds\n" + t.groupby(["price", "k"])[["gross_bp_day", "t"]].mean().round(3).to_string())

    rows = []
    for sym in DISC + HOLD:
        df = load_klines_local(sym, START, END)
        o, hi, lo, cl = ohlc_arrays(df)
        last, days = day_end_bars(df.index)
        fund = load_funding_local(sym, START, END)
        fb = df.index.searchsorted(pd.DatetimeIndex(fund["time"]) - pd.Timedelta(minutes=1))
        ok = fb < len(df)
        for k, h in ((0.01, 6), (0.02, 6)):
            for fill in ("through", "touch"):
                d = daily_pnl(run_neutral(o, hi, lo, cl, k, h, fill=fill), cl, last, fb[ok], fund["rate"].to_numpy()[ok])
                rows.append(dict(symbol=sym, combo=f"k{k:g}_h{h}", fill=fill, net_ann=d["net"].mean() * 365,
                                 net_sharpe=sharpe(d["net"]), gross_ann=d["gross"].mean() * 365,
                                 gross_sharpe=sharpe(d["gross"])))
    t = pd.DataFrame(rows)
    L.append("\n(b) fill rule sensitivity on real data (capital 1)\n" + t.round(3).to_string(index=False))
    t["basket"] = np.where(t.symbol.isin(DISC), "disc", "hold")
    L.append("\nbasket means (avg over symbols)\n" + t.groupby(["basket", "combo", "fill"])[
        ["net_ann", "gross_ann", "net_sharpe", "gross_sharpe"]].mean().round(3).to_string())
    txt = "\n".join(L)
    (OUT / "summary.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
