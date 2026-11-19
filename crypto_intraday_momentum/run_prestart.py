"""Does anchoring the session earlier than the 09:30 NY open help?

The session window [start, 16:00 NY] is varied and everything else stays the same:
the open anchor, the band, VWAP and the decisions all start at `start`. The
entry cutoff stays at 14:00 NY wall-clock time.

    python -m crypto_intraday_momentum.run_prestart
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

OUT = Path(__file__).parent / "results" / "prestart"
PPY, WARMUP = 252, 31
STARTS = ["06:00", "07:00", "08:00", "08:30", "09:00", "09:30"]
SETS = {"discovery(BTC+ETH+SOL)": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "holdout(BNB+XRP+DOGE)": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}


def _min(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def spec_for(start: str) -> SessionSpec:
    return SessionSpec(f"us_{start}", "America/New_York", start, _min("16:00") - _min(start), "xnys")


def rules(start: str) -> dict:
    return {
        "base": {},
        "filtered": dict(entry_cutoff_min=_min("14:00") - _min(start), vwap_confirm_k=0.6),
    }


def _one(sym, start_date, end_date, exec_name):
    df = load_klines(sym, start_date, end_date)
    fund = load_funding(sym, start_date, end_date)
    rets, rows, trades = {}, [], []
    common = None
    for st in STARTS:
        m = build_sessions(df, spec_for(st))
        s = compute_signals(m)
        for rname, kw in rules(st).items():
            res = run_backtest(m, s, Config(tick=TICKS.get(sym, 0.01), **EXEC[exec_name], **kw), fund)
            r = pd.Series(res.sessions["ret"].where(res.sessions["active"], 0.0).to_numpy(),
                          index=m.dates).iloc[WARMUP:]
            rets[f"{st}_{rname}"] = r
            sm = summarize(res, PPY)
            rows.append(dict(symbol=sym, start=st, rule=rname, **{k: sm.get(k) for k in (
                "trades", "sharpe", "avg_bps_per_trade", "t_stat", "max_drawdown")}))
            t = res.trades.assign(symbol=sym, start=st, rule=rname)
            t["clock"] = (pd.Timestamp("2000-01-01") + pd.to_timedelta(_min(st) + t["dec_min"], "min")).dt.strftime("%H:%M")
            t["net_bps"] = t["ret_notional"] * 1e4
            trades.append(t[["symbol", "start", "rule", "clock", "net_bps", "ret_equity", "date"]])
    R = pd.DataFrame(rets).dropna()
    return sym, R, rows, pd.concat(trades)


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
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(_one, syms, [a.start] * n, [a.end] * n, [a.exec] * n))
    R = {s: r for s, r, _, _ in res}
    per = pd.DataFrame([x for _, _, rows, _ in res for x in rows])
    T = pd.concat([t for *_, t in res])
    per.to_csv(OUT / "per_symbol.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    lines = []

    def show(title, obj):
        txt = f"\n### {title}\n{obj if isinstance(obj, str) else obj.round(2).to_string()}"
        print(txt, flush=True); lines.append(txt)

    show("per-symbol Sharpe (rows: start, cols: symbol x rule)",
         per.pivot_table(index="start", columns=["rule", "symbol"], values="sharpe"))
    show("per-symbol net bps / trade",
         per.pivot_table(index="start", columns=["rule", "symbol"], values="avg_bps_per_trade"))
    for name, members in SETS.items():
        idx = R[members[0]].index
        for s in members[1:]:
            idx = idx.intersection(R[s].index)
        B = sum(R[s].loc[idx] for s in members) / len(members)
        tab = pd.DataFrame({
            "sharpe": B.apply(_sr),
            "mean_bps": B.mean() * 1e4,
            "t": B.mean() / B.std(ddof=1) * np.sqrt(len(B)),
        })
        tab.index = pd.MultiIndex.from_tuples([tuple(c.split("_")) for c in tab.index], names=["start", "rule"])
        show(f"{name}: basket by session start", tab.unstack("rule"))
        for rule in ("base", "filtered"):
            cols = [c for c in B.columns if c.endswith(rule)]
            cv = run_cpcv(B[cols], 10, 2, 30)
            psr = cv.paths.apply(_sr)
            show(f"{name}: CPCV choosing the start time ({rule})",
                 f"PBO={cv.pbo:.2f}  OOS path SR mean={psr.mean():.2f} min={psr.min():.2f}\nchosen: "
                 + ", ".join(f"{k}({v})" for k, v in cv.chosen.combo.value_counts().items()))
        yr = pd.DataFrame({c: B[c].groupby(B.index.year).apply(lambda x: (np.prod(1 + x) - 1) * 100)
                           for c in ["09:30_filtered", "08:30_filtered", "08:00_filtered", "07:00_filtered"]})
        show(f"{name}: yearly return % (filtered)", yr)
        TT = T[T.symbol.isin(members)]
        for st in ("08:00", "08:30"):
            g = TT[(TT.start == st) & (TT.rule == "base")].groupby("clock")["net_bps"]
            show(f"{name}: start {st} (base rules) net bps by decision clock time",
                 pd.DataFrame({"n": g.size(), "net_bps": g.mean(),
                               "t": g.mean() / g.std(ddof=1) * np.sqrt(g.size())}).T)
    (OUT / "report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
