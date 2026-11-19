"""Anchored walk-forward validation of the whole design process.

At the start of every test period the configuration is chosen using ONLY data
before that period, then applied to the period. The test segments are joined
into one out-of-sample equity curve.

  candidates : entry rules (cutoff x VWAP-k) x sizing scheme   -> best train Sharpe
  throttle   : dd_max in {none, 10%, 15%, 20%}                  -> best train Calmar
  fixed      : session 09:30-16:00 NY, maker_chase execution, BTC+ETH+SOL equal weight,
               25% portfolio vol target (a risk preference, not optimised), 3x per-trade cap

Comparators on the same out-of-sample window:
  baseline : the paper's rules with paper sizing at the same vol target and no throttle
  final    : the hand-picked configuration (chosen on data through 2026-10, so it is
             in-sample except for 2026-11)

    python -m crypto_intraday_momentum.walkforward
"""
from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Config
from .cpcv import EXEC
from .data import load_funding, load_klines
from .run import TICKS
from .run_sizing import build_portfolio
from .sessions import US, build_sessions
from .signals import compute_signals
from .sizing import metrics, pre_open_rv, unit_trades

OUT = Path(__file__).parent / "results" / "walkforward"
PPY = 252
CUTOFFS = {"none": None, "13:30": 240, "14:00": 270, "14:30": 300}
VWAP_K = [0.0, 0.3, 0.6]
SCHEMES = ["paper", "rv24", "risk_per_trade"]
DDS = [None, 0.10, 0.15, 0.20]
TARGET, MAX_LEV = 0.25, 3.0
BASELINE = ("none", 0.0, "paper", None)
FINAL = ("14:00", 0.6, "rv24", 0.15)
PERIODS = [("2022", "2022-01-01", "2022-12-31"), ("2023", "2023-01-01", "2023-12-31"),
           ("2024", "2024-01-01", "2024-12-31"), ("2025", "2025-01-01", "2025-12-31"),
           ("2026 Jan-Oct", "2026-01-01", "2026-10-31"), ("2026 Nov (unseen)", "2026-11-01", "2026-11-30")]


def throttle_tv(r: pd.Series, dd: pd.Series, floor: float = 0.25) -> pd.Series:
    """Drawdown throttle with a time-varying dd_max (NaN = off), run causally."""
    x, d = r.to_numpy(), dd.to_numpy()
    out = np.empty_like(x)
    eq = peak = 1.0
    for k in range(len(x)):
        g = 1.0 if not np.isfinite(d[k]) else min(1.0, max(floor, 1 - (1 - eq / peak) / d[k]))
        out[k] = g * x[k]
        eq *= 1 + out[k]
        peak = max(peak, eq)
    return pd.Series(out, index=r.index)


def candidate_series(symbols, start, end, exec_name="maker_chase") -> dict:
    """Raw (un-throttled) portfolio session returns for every rule x scheme candidate."""
    loaded = {}
    for sym in symbols:
        df = load_klines(sym, start, end)
        fund = load_funding(sym, start, end)
        m = build_sessions(df, US)
        loaded[sym] = (m, compute_signals(m), fund, pre_open_rv(df, m))
    out = {}
    for c, k in product(CUTOFFS, VWAP_K):
        data = {}
        for sym, (m, s, fund, rv) in loaded.items():
            cfg = Config(tick=TICKS.get(sym, 0.01), entry_cutoff_min=CUTOFFS[c], vwap_confirm_k=k,
                         **EXEC[exec_name])
            data[sym] = (m, unit_trades(m, s, cfg, fund), rv)
        for sc in SCHEMES:
            r, _ = build_portfolio(data, sc, "equal", TARGET, MAX_LEV)
            out[(c, k, sc)] = r
    return out


def _sr(x):
    return x.mean() / x.std(ddof=1) * np.sqrt(PPY) if len(x) > 2 and x.std() > 0 else np.nan


def _calmar(x):
    m = metrics(x)
    return m["calmar"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-11")
    ap.add_argument("--warmup", type=int, default=60, help="sessions dropped after vol-target warm-up")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    C = candidate_series(a.symbols, a.start, a.end)
    R = pd.DataFrame({k: v for k, v in C.items()}).iloc[a.warmup:]
    R.columns = pd.MultiIndex.from_tuples(R.columns, names=["cutoff", "vwap_k", "scheme"])
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    lines = []

    def show(title, obj):
        txt = f"\n### {title}\n{obj if isinstance(obj, str) else obj.round(3).to_string()}"
        print(txt, flush=True); lines.append(txt)

    oos_raw, oos_dd, picks = [], [], []
    for name, a0, a1 in PERIODS:
        train = R[R.index < pd.Timestamp(a0)]
        test = R[(R.index >= pd.Timestamp(a0)) & (R.index <= pd.Timestamp(a1))]
        if test.empty:
            continue
        srs = train.apply(_sr)
        best = srs.idxmax()
        cal = {}
        for dd in DDS:
            x = train[best] if dd is None else throttle_tv(train[best], pd.Series(dd, index=train.index))
            cal[dd] = _calmar(x)
        dd_best = max(cal, key=lambda d: cal[d])
        picks.append(dict(period=name, train_sessions=len(train), cutoff=best[0], vwap_k=best[1],
                          scheme=best[2], train_sharpe=srs.max(), dd=dd_best or "-",
                          train_calmar=cal[dd_best], test_sessions=len(test)))
        oos_raw.append(test[best])
        oos_dd.append(pd.Series(np.nan if dd_best is None else dd_best, index=test.index))
    show("walk-forward choices (chosen only from data before each period)", pd.DataFrame(picks).set_index("period"))

    wf = throttle_tv(pd.concat(oos_raw), pd.concat(oos_dd))
    idx = wf.index
    base = R[BASELINE[:3]].reindex(idx)
    fin = throttle_tv(R[FINAL[:3]].reindex(idx), pd.Series(FINAL[3], index=idx))
    fin_nothr = R[FINAL[:3]].reindex(idx)
    curves = {"walk-forward (OOS)": wf, "final config": fin, "final w/o throttle": fin_nothr,
              "baseline (paper rules+sizing)": base}
    show("whole out-of-sample window 2022-01 .. 2026-11",
         pd.DataFrame({k: metrics(v) for k, v in curves.items()}).T)
    per = {}
    for name, a0, a1 in PERIODS:
        msk = (idx >= pd.Timestamp(a0)) & (idx <= pd.Timestamp(a1))
        per[name] = {k: (np.prod(1 + v[msk]) - 1) * 100 for k, v in curves.items()}
        per[name]["sessions"] = int(msk.sum())
    show("return % by period", pd.DataFrame(per).T)
    per_sr = {name: {k: _sr(v[(idx >= pd.Timestamp(a0)) & (idx <= pd.Timestamp(a1))]) for k, v in curves.items()}
              for name, a0, a1 in PERIODS}
    show("Sharpe by period", pd.DataFrame(per_sr).T)
    d = wf - base
    show("walk-forward vs baseline", f"paired diff t-stat = {d.mean() / d.std(ddof=1) * np.sqrt(len(d)):.2f}")
    pd.DataFrame(curves).to_parquet(OUT / "oos_curves.parquet")
    (OUT / "report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
