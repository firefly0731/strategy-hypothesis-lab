"""Hold trend positions past the 16:00 NY close?

Entry signal is unchanged (09:30 anchor, 16:00 reference close for gap/vol, entry
cutoff 14:00, VWAP 0.6 sigma). Only the exit horizon and the post-close rule change:
  trail       : keep the paper's trailing stop (band / VWAP) every 30 min
  profit_only : at 16:00 close losers, then trail the winners
  hold        : no stop after 16:00, exit at the extended session end

    python -m crypto_intraday_momentum.run_extend
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
from .report import summarize
from .run import TICKS
from .sessions import SessionSpec, build_sessions
from .signals import compute_signals

OUT = Path(__file__).parent / "results" / "extend"
PPY, WARMUP, REF = 252, 31, 390
ENDS = {"16:00": 390, "18:00": 510, "20:00": 630, "24:00": 870, "+04:00": 1110, "+08:00": 1350}
RULES_POST = ["trail", "profit_only", "hold"]
ENTRY = dict(entry_cutoff_min=270, vwap_confirm_k=0.6)
SETS = {"discovery(BTC+ETH+SOL)": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "holdout(BNB+XRP+DOGE)": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}


def configs():
    yield "16:00", "-", 390
    for e, n in ENDS.items():
        if n > REF:
            for r in RULES_POST:
                yield e, r, n


def _one(sym, start, end, exec_name):
    df = load_klines(sym, start, end)
    fund = load_funding(sym, start, end)
    cache, rets, rows, post = {}, {}, [], []
    for e, rule, n in configs():
        if n not in cache:
            m = build_sessions(df, SessionSpec(f"us_{n}", "America/New_York", "09:30", n, "xnys"))
            cache[n] = (m, compute_signals(m, ref_close_min=REF))
        m, s = cache[n]
        kw = dict(post_close_min=REF, post_close_rule=rule) if n > REF else {}
        res = run_backtest(m, s, Config(tick=TICKS.get(sym, 0.01), **EXEC[exec_name], **ENTRY, **kw), fund)
        key = f"{e}|{rule}"
        rets[key] = pd.Series(res.sessions["ret"].where(res.sessions["active"], 0.0).to_numpy(),
                              index=m.dates).iloc[WARMUP:]
        st = summarize(res, PPY)
        t = res.trades
        held = t[(t["exit_time"] - pd.DatetimeIndex(m.start_utc[t["sess_idx"]]))
                 / pd.Timedelta(minutes=1) > REF] if len(t) else t
        rows.append(dict(symbol=sym, end=e, rule=rule, trades=st["trades"], sharpe=st["sharpe"],
                         bps=st["avg_bps_per_trade"], t=st["t_stat"], mdd=st["max_drawdown"],
                         win=st.get("win_rate"), held_past_close=len(held),
                         avg_hold_h=t["hold_min"].mean() / 60 if len(t) else np.nan,
                         funding_bps=(t["funding"] / t["notional"]).mean() * 1e4 if len(t) else np.nan))
        if len(held):   # P&L earned after 16:00 on trades that were held past it (unit notional)
            i = held["sess_idx"].to_numpy()
            p16 = m.C[i, REF - 1]
            post.append(dict(symbol=sym, end=e, rule=rule, n=len(held),
                             post_close_bps=(held["side"] * (held["exit_px"] / p16 - 1)).mean() * 1e4,
                             post_t=((held["side"] * (held["exit_px"] / p16 - 1)).mean()
                                     / (held["side"] * (held["exit_px"] / p16 - 1)).std(ddof=1) * np.sqrt(len(held)))))
    return sym, pd.DataFrame(rets), rows, post


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
    n = len(syms)
    with ProcessPoolExecutor(3) as ex:
        res = list(ex.map(_one, syms, [a.start] * n, [a.end] * n, [a.exec] * n))
    R = {s: r for s, r, _, _ in res}
    per = pd.DataFrame([x for _, _, rows, _ in res for x in rows])
    post = pd.DataFrame([x for *_, p in res for x in p])
    per.to_csv(OUT / "per_symbol.csv", index=False)
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    lines = []

    def show(title, obj):
        txt = f"\n### {title}\n{obj if isinstance(obj, str) else obj.round(2).to_string()}"
        print(txt, flush=True); lines.append(txt)

    show("per-symbol Sharpe", per.pivot_table(index=["end", "rule"], columns="symbol", values="sharpe", sort=False))
    show("per-symbol net bps / trade", per.pivot_table(index=["end", "rule"], columns="symbol", values="bps", sort=False))
    show("avg holding hours / funding bps per trade (BTC)",
         per[per.symbol == "BTCUSDT"].set_index(["end", "rule"])[["held_past_close", "avg_hold_h", "funding_bps", "win"]])
    show("P&L earned AFTER 16:00 on trades held past it (bps of notional, pooled by set)",
         post.assign(set=post.symbol.map({s: k for k, v in SETS.items() for s in v}))
         .groupby(["set", "end", "rule"], sort=False)
         .apply(lambda g: pd.Series({"n": g.n.sum(), "bps": np.average(g.post_close_bps, weights=g.n)})).unstack(0))
    for name, members in SETS.items():
        idx = R[members[0]].index
        for s in members[1:]:
            idx = idx.intersection(R[s].index)
        B = (sum(R[s].loc[idx] for s in members) / len(members)).dropna()
        tab = pd.DataFrame({"sharpe": B.apply(_sr), "mean_bps": B.mean() * 1e4,
                            "t": B.mean() / B.std(ddof=1) * np.sqrt(len(B)),
                            "mdd": B.apply(lambda x: ((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min())})
        show(f"{name}: basket", tab)
        yr = B.groupby(B.index.year).apply(lambda x: x.mean() / x.std(ddof=1) * np.sqrt(PPY)).T
        show(f"{name}: yearly Sharpe", yr)
        base = B["16:00|-"]
        dt = {c: ((B[c] - base).mean() / (B[c] - base).std(ddof=1) * np.sqrt(len(B))) for c in B if c != "16:00|-"}
        show(f"{name}: paired t of session-return difference vs 16:00", pd.Series(dt).to_frame("t"))
        cv = run_cpcv(B, 10, 2, 30)
        psr = cv.paths.apply(_sr)
        show(f"{name}: CPCV over {B.shape[1]} configs",
             f"PBO={cv.pbo:.2f} OOS path SR mean={psr.mean():.2f} min={psr.min():.2f}\nchosen: "
             + ", ".join(f"{k}({v})" for k, v in cv.chosen.combo.value_counts().head(5).items()))
    (OUT / "report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
