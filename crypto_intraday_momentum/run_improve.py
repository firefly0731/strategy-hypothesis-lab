"""Validate the entry-cutoff and VWAP-confirmation filters.

The rules were found on BTC/ETH/SOL (discovery set). BNB/XRP/DOGE were not used
in that analysis and serve as a hold-out set. For both sets this script reports
the threshold sensitivity grid, CPCV over the grid (PBO, OOS path Sharpe) and a
yearly comparison.

    python -m crypto_intraday_momentum.run_improve
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Config, run_backtest
from .cpcv import EXEC, run_cpcv
from .data import load_funding, load_klines
from .report import summarize
from .run import TICKS
from .sessions import US, build_sessions
from .signals import compute_signals

OUT = Path(__file__).parent / "results" / "improve"
PPY, WARMUP = 252, 31
CUTOFFS = {"none": None, "13:00": 210, "13:30": 240, "14:00": 270, "14:30": 300}
VWAP_K = [0.0, 0.3, 0.6, 0.9]
GRID = [(c, k) for c, k in product(CUTOFFS, VWAP_K)]
BASELINE, PROPOSED = "cut=none_vk=0", "cut=14:00_vk=0.6"
SETS = {"discovery(BTC+ETH+SOL)": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "holdout(BNB+XRP+DOGE)": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}


def label(c, k):
    return f"cut={c}_vk={k:g}"


def _one(sym, start, end, exec_name):
    df = load_klines(sym, start, end)
    fund = load_funding(sym, start, end)
    m = build_sessions(df, US)
    s = compute_signals(m)
    rets, rows = {}, []
    for c, k in GRID:
        cfg = Config(tick=TICKS.get(sym, 0.01), entry_cutoff_min=CUTOFFS[c], vwap_confirm_k=k,
                     **EXEC[exec_name])
        res = run_backtest(m, s, cfg, fund)
        rets[label(c, k)] = res.sessions["ret"].where(res.sessions["active"], 0.0).to_numpy()[WARMUP:]
        st = summarize(res, PPY)
        rows.append(dict(symbol=sym, cutoff=c, vwap_k=k, **{x: st.get(x) for x in (
            "trades", "sharpe", "avg_bps_per_trade", "t_stat", "max_drawdown", "total_return")}))
    return sym, pd.DataFrame(rets, index=m.dates[WARMUP:]), rows


def _sr(x):
    return x.mean() / x.std(ddof=1) * np.sqrt(PPY)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--exec", default="maker_chase", choices=list(EXEC))
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    syms = [s for v in SETS.values() for s in v]
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(_one, syms, [a.start] * len(syms), [a.end] * len(syms),
                          [a.exec] * len(syms)))
    R = {s: r for s, r, _ in res}
    per_sym = pd.DataFrame([row for *_, rows in res for row in rows])
    per_sym.to_csv(OUT / "per_symbol.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    lines = []

    def show(title, obj):
        txt = f"\n### {title}\n{obj if isinstance(obj, str) else obj.round(2).to_string()}"
        print(txt, flush=True); lines.append(txt)

    show("per symbol: baseline vs proposed (cutoff 14:00, vwap_k 0.6)",
         per_sym[((per_sym.cutoff == "none") & (per_sym.vwap_k == 0)) |
                 ((per_sym.cutoff == "14:00") & (per_sym.vwap_k == 0.6))]
         .set_index(["symbol", "cutoff", "vwap_k"]))
    summary = []
    for name, members in SETS.items():
        idx = R[members[0]].index
        for s in members[1:]:
            idx = idx.intersection(R[s].index)
        B = sum(R[s].loc[idx] for s in members) / len(members)
        B.to_parquet(OUT / f"basket_{name.split('(')[0]}.parquet")
        sr = B.apply(_sr)
        heat = pd.DataFrame([[sr[label(c, k)] for k in VWAP_K] for c in CUTOFFS],
                            index=[f"cutoff {c}" for c in CUTOFFS], columns=[f"vwap_k {k:g}" for k in VWAP_K])
        show(f"{name}: full-sample Sharpe grid (equal-weight basket)", heat)
        bps = pd.DataFrame([[B[label(c, k)].mean() * 1e4 for k in VWAP_K] for c in CUTOFFS],
                           index=heat.index, columns=heat.columns)
        show(f"{name}: mean session return (bps of equity)", bps)
        cv = run_cpcv(B, 10, 2, 30)
        psr = cv.paths.apply(_sr)
        yr = pd.DataFrame({
            "baseline": B[BASELINE].groupby(B.index.year).apply(lambda x: (np.prod(1 + x) - 1) * 100),
            "proposed": B[PROPOSED].groupby(B.index.year).apply(lambda x: (np.prod(1 + x) - 1) * 100),
            "cpcv_avg_path": cv.paths.mean(axis=1).groupby(B.index.year).apply(
                lambda x: (np.prod(1 + x) - 1) * 100),
        })
        show(f"{name}: yearly return %", yr)
        d = B[PROPOSED] - B[BASELINE]
        info = (f"PBO={cv.pbo:.2f}  OOS path Sharpe mean={psr.mean():.2f} min={psr.min():.2f} "
                f"max={psr.max():.2f}\nbaseline SR={sr[BASELINE]:.2f}  proposed SR={sr[PROPOSED]:.2f}  "
                f"diff t-stat={d.mean() / d.std(ddof=1) * np.sqrt(len(d)):.2f}\n"
                "chosen: " + ", ".join(f"{k}({v})" for k, v in cv.chosen.combo.value_counts().head(4).items()))
        show(f"{name}: CPCV over {len(GRID)} configs", info)
        summary.append(dict(set=name, pbo=cv.pbo, path_sr_mean=psr.mean(), path_sr_min=psr.min(),
                            baseline_sr=sr[BASELINE], proposed_sr=sr[PROPOSED],
                            best_cfg=sr.idxmax(), best_sr=sr.max(),
                            diff_t=d.mean() / d.std(ddof=1) * np.sqrt(len(d))))
    pd.DataFrame(summary).to_csv(OUT / "summary.csv", index=False)
    (OUT / "report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
