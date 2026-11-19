"""CPCV + regime decomposition.

    python -m crypto_intraday_momentum.run_cpcv --symbols BTCUSDT ETHUSDT SOLUSDT
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .cpcv import (default_grid, grid_session_returns, market_session_returns,
                   regime_decomposition, run_cpcv)
from .data import load_funding, load_klines
from .run import TICKS
from .sessions import US, build_sessions

PPY = 252
DEFAULT = "lb14_iv30_maker_chase_cf0"
OUT = Path(__file__).parent / "results" / "cpcv"


def _grid(sym, start, end):
    path = OUT / f"grid_{sym}.parquet"
    mpath = OUT / f"mkt_{sym}.parquet"
    if path.exists() and mpath.exists():
        return sym, pd.read_parquet(path), pd.read_parquet(mpath)
    df = load_klines(sym, start, end)
    fund = load_funding(sym, start, end)
    m = build_sessions(df, US)
    R = grid_session_returns(m, fund, TICKS.get(sym, 0.01), default_grid())
    mk = market_session_returns(m)
    R.to_parquet(path); mk.to_parquet(mpath)
    return sym, R, mk


def _fmt(d: dict) -> str:
    keys = ["raw_mean_bps", "raw_sharpe", "raw_t", "beta_mkt", "beta_mkt_t", "alpha_dir_bps",
            "alpha_dir_t", "alpha_dir_sharpe", "alpha_exante_bps", "alpha_exante_t",
            "beta_trend60_t", "beta_vol20_t", "regime_balanced_bps", "alpha_absmkt_bps",
            "alpha_absmkt_t", "beta_absmkt_t"]
    return "  ".join(f"{k}={d[k]:.3g}" for k in keys)


def analyse(name, R, mk, n_groups, k_test, embargo, log):
    res = run_cpcv(R, n_groups, k_test, embargo)
    path_sr = res.paths.apply(lambda x: x.mean() / x.std(ddof=1) * np.sqrt(PPY))
    avg_path = res.paths.mean(axis=1)
    dec = regime_decomposition(avg_path, mk, PPY)
    fixed = regime_decomposition(R[DEFAULT], mk, PPY)
    full_sr = R.apply(lambda x: x.mean() / x.std(ddof=1) * np.sqrt(PPY))
    log(f"\n=== {name}  sessions={len(R)}  combos={R.shape[1]}  splits={len(res.chosen)}  paths={res.paths.shape[1]}")
    log(f"PBO={res.pbo:.2f}   OOS path Sharpe: mean={path_sr.mean():.2f} "
        f"min={path_sr.min():.2f} p25={path_sr.quantile(.25):.2f} max={path_sr.max():.2f}")
    log(f"in-sample best combo (full history) = {full_sr.idxmax()} SR={full_sr.max():.2f};"
        f"  default {DEFAULT} SR={full_sr[DEFAULT]:.2f}")
    log("most chosen combos: " + ", ".join(f"{k}({v})" for k, v in
                                           res.chosen["combo"].value_counts().head(5).items()))
    log("CPCV avg OOS path   : " + _fmt(dec))
    log("default (no select.): " + _fmt(fixed))
    log("ex-ante regime cells (avg OOS path):\n" + dec["regime_table"].round(2).to_string())
    log("same-session |move| terciles (avg OOS path):\n" + dec["move_table"].round(2).to_string())
    by_year = avg_path.groupby(avg_path.index.year).apply(
        lambda x: pd.Series({"ret%": (np.prod(1 + x) - 1) * 100,
                             "SR": x.mean() / x.std(ddof=1) * np.sqrt(PPY)})).unstack()
    log("avg OOS path by year:\n" + by_year.round(2).T.to_string())
    return dict(name=name, pbo=res.pbo, path_sr_mean=path_sr.mean(), path_sr_min=path_sr.min(),
                **{k: v for k, v in dec.items() if not isinstance(v, pd.DataFrame)})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+",
                    default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"])
    ap.add_argument("--basket", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--groups", type=int, default=10)
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--embargo", type=int, default=30)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    lines = []

    def log(s):
        print(s, flush=True); lines.append(s)

    with ProcessPoolExecutor(4) as ex:
        data = {s: (R, mk) for s, R, mk in ex.map(_grid, a.symbols,
                                                 [a.start] * len(a.symbols), [a.end] * len(a.symbols))}
    rows = [analyse(s, R, mk, a.groups, a.k, a.embargo, log) for s, (R, mk) in data.items()]
    bk = [s for s in a.basket if s in data]
    if len(bk) > 1:
        idx = data[bk[0]][0].index
        for s in bk[1:]:
            idx = idx.intersection(data[s][0].index)
        R = sum(data[s][0].loc[idx] for s in bk) / len(bk)
        mk = sum(data[s][1].loc[idx] for s in bk) / len(bk)
        rows.append(analyse("BASKET(" + "+".join(x.replace("USDT", "") for x in bk) + ")",
                            R, mk, a.groups, a.k, a.embargo, log))
    pd.DataFrame(rows).to_csv(OUT / "cpcv_summary.csv", index=False)
    (OUT / "cpcv_report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
