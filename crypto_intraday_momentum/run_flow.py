"""Order-flow confirmation: attribution and filter validation.

  stage 1 (attribution): trade P&L by quintile of the side-aligned flow feature
  stage 2 (validation) : filter side*feature >= threshold, sensitivity grid,
                         hold-out set, CPCV, yearly Sharpe

    python -m crypto_intraday_momentum.run_flow
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Config, run_backtest
from .cpcv import EXEC, run_cpcv
from .data import load_funding, load_klines
from .flow import flow_features
from .run import TICKS
from .sessions import US, build_sessions
from .signals import compute_signals

OUT = Path(__file__).parent / "results" / "flow"
PPY, WARMUP = 252, 31
ADOPTED = dict(entry_cutoff_min=270, vwap_confirm_k=0.6)
SETS = {"discovery(BTC+ETH+SOL)": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "holdout(BNB+XRP+DOGE)": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}
FEATS = ["imb_open", "imb_last", "imb_open_z"]


def _trades(sym, start, end, exec_name):
    df = load_klines(sym, start, end)
    fund = load_funding(sym, start, end)
    m = build_sessions(df, US)
    s = compute_signals(m)
    f = flow_features(m, s.dec_min)
    out = []
    for rname, kw in (("base", {}), ("adopted", ADOPTED)):
        t = run_backtest(m, s, Config(tick=TICKS.get(sym, 0.01), **EXEC[exec_name], **kw), fund).trades
        i, j, side = t["sess_idx"].to_numpy(), t["dec_j"].to_numpy(), t["side"].to_numpy()
        t = t.assign(symbol=sym, rules=rname, net_bps=t["ret_notional"] * 1e4,
                     gross_bps=t["gross"] / t["notional"] * 1e4,
                     **{k: side * f[k][i, j] for k in FEATS})
        out.append(t)
    return pd.concat(out)


def attribution(T: pd.DataFrame, show):
    T = T.assign(set=T.symbol.map({s: k for k, v in SETS.items() for s in v}))
    for rules in ("base", "adopted"):
        for feat in FEATS:
            rows = []
            for st, g in T[T.rules == rules].groupby("set"):
                g = g.dropna(subset=[feat])
                q = pd.qcut(g[feat], 5, labels=[f"Q{k}" for k in range(1, 6)])
                gg = g.groupby(q, observed=True)
                tab = pd.DataFrame({"n": gg.size(), "edge": gg[feat].median(), "net_bps": gg.net_bps.mean(),
                                    "t": gg.net_bps.mean() / gg.net_bps.std(ddof=1) * np.sqrt(gg.size())})
                tab.columns = pd.MultiIndex.from_product([[st], tab.columns])
                rows.append(tab)
            show(f"[{rules} rules] net bps by quintile of side*{feat}", pd.concat(rows, axis=1))
        # per symbol: aligned (>0) vs against (<=0) for the since-open imbalance
        g = T[T.rules == rules].assign(aligned=lambda d: np.where(d.imb_open > 0, "with flow", "against flow"))
        show(f"[{rules} rules] since-open imbalance aligned vs against, by symbol",
             g.pivot_table(index="aligned", columns="symbol", values="net_bps", aggfunc=["mean", "count"]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--exec", default="maker_chase", choices=list(EXEC))
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    syms = [s for v in SETS.values() for s in v]
    n = len(syms)
    with ProcessPoolExecutor(3) as ex:
        T = pd.concat(ex.map(_trades, syms, [a.start] * n, [a.end] * n, [a.exec] * n))
    T.to_parquet(OUT / "trades_flow.parquet")
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    lines = []

    def show(title, obj):
        txt = f"\n### {title}\n{obj if isinstance(obj, str) else obj.round(3).to_string()}"
        print(txt, flush=True); lines.append(txt)

    attribution(T, show)
    (OUT / "attribution.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
