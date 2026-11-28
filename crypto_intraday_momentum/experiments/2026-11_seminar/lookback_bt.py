"""Sigma lookback window {7,10,14,21,30} sessions with the production rules (30-min decisions,
14:00 cutoff, VWAP 0.6 sigma, maker_chase). Discovery BTC/ETH/SOL and hold-out BNB/XRP/DOGE.
Reports 1x unit basket, production-sized portfolio (rv24, 25% vol, 3x cap, dd 15%) and the
paired difference vs lookback 14 (session-level t, per-year t).

Stage (one symbol per process, keeps memory low):  python lookback_bt.py OUT SYMBOL
Report:                                             python lookback_bt.py OUT
All variants start at the same session (warmup 31 >= max lookback 30), so the samples match."""
import json, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from crypto_intraday_momentum.backtest import Config
from crypto_intraday_momentum.cpcv import EXEC
from crypto_intraday_momentum.data import load_funding, load_klines
from crypto_intraday_momentum.run import TICKS
from crypto_intraday_momentum.sessions import US, build_sessions
from crypto_intraday_momentum.signals import compute_signals
from crypto_intraday_momentum.sizing import pre_open_rv, unit_trades
from crypto_intraday_momentum.run_sizing import build_portfolio, RULES

OUT = sys.argv[1]; PPY = 252
SETS = {"discovery": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "holdout": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}
LOOKBACKS = [7, 10, 14, 21, 30]
BASE = 14


def mt(r):
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1
    return dict(cagr=eq.iloc[-1] ** (PPY / len(r)) - 1, vol=r.std() * np.sqrt(PPY),
                sharpe=r.mean() / r.std() * np.sqrt(PPY), mdd=dd.min())


def tstat(d):
    d = d.dropna()
    return d.mean() / d.std() * np.sqrt(len(d)) if len(d) > 2 and d.std() > 0 else np.nan


if len(sys.argv) > 2:
    sym = sys.argv[2]
    df = load_klines(sym, "2021-01", "2026-10"); fund = load_funding(sym, "2021-01", "2026-10")
    m = build_sessions(df, US); rv = pre_open_rv(df, m)
    cfg = Config(tick=TICKS.get(sym, 0.01), **EXEC["maker_chase"], **RULES)
    out = {lb: unit_trades(m, compute_signals(m, lookback=lb), cfg, fund) for lb in LOOKBACKS}
    pd.to_pickle(dict(m=m, rv=rv, t=out), f"{OUT}/LB_{sym}.pkl"); print("saved", sym); sys.exit(0)

res = {}
for set_name, syms in SETS.items():
    D = {s: pd.read_pickle(f"{OUT}/LB_{s}.pkl") for s in syms}
    if set_name == "discovery":               # lookback 14 must reproduce the stored production run
        for s in syms:
            try:
                ref = pd.read_pickle(f"{OUT}/IV_{s}.pkl")["t"]["30m"]
            except FileNotFoundError:
                print(f"check SKIPPED: no IV_{s}.pkl (run interval_bt.py first)")
                continue
            a = D[s]["t"][BASE]
            assert len(a) == len(ref) and np.allclose(a.pnl, ref.pnl), s
            print("check ok: lookback 14 == stored production run,", s)
    SER = {}; res[set_name] = {}
    for lb in LOOKBACKS:
        data = {s: (D[s]["m"], D[s]["t"][lb], D[s]["rv"]) for s in syms}
        T = pd.concat([t.assign(sym=s) for s, (_, t, _) in data.items()])
        U = pd.DataFrame({s: t.groupby("sess_idx").ret_notional.sum().reindex(range(D[s]["m"].n)).fillna(0.0)
                          .set_axis(D[s]["m"].dates) for s, (_, t, _) in data.items()}).fillna(0.0).iloc[31 + 60:]
        u = U.mean(axis=1)
        r, _ = build_portfolio(data, "rv24", "equal", 0.25, 3.0, 0.15, scale_cap=20.0)
        r = r.iloc[60:]
        T = T[T.date >= u.index[0]]
        weeks = len(u) / PPY * 52
        SER[lb] = (u, r)
        res[set_name][lb] = dict(unit=mt(u), prod=mt(r), trades_per_week=len(T) / weeks, n=len(T),
                                 net_bp=T.ret_notional.mean() * 1e4, win=(T.pnl > 0).mean(),
                                 stop_share=(T.exit_reason == "stop").mean(),
                                 yearly_unit=u.groupby(u.index.year).apply(
                                     lambda x: x.mean() / x.std() * np.sqrt(PPY)).round(2).to_dict(),
                                 span=[str(u.index[0].date()), str(u.index[-1].date())])
    for lb in LOOKBACKS:
        row = res[set_name][lb]
        for lab, idx in (("unit", 0), ("prod", 1)):
            a, b = SER[BASE][idx], SER[lb][idx]
            d = (b - a).dropna()
            row[f"diff_{lab}"] = dict(bp_per_day=d.mean() * 1e4, t=tstat(d), corr=a.corr(b),
                                      per_year_t=d.groupby(d.index.year).apply(tstat).round(2).to_dict())
        if set_name == "holdout" and lb == BASE:   # must reproduce the deck's hold-out production run
            try:
                ref = json.load(open(f"{OUT}/deck.json"))["hold_maker"]["metrics"]["sharpe"]
                assert np.isclose(row["prod"]["sharpe"], ref), (row["prod"]["sharpe"], ref)
                print("check ok: hold-out lookback 14 == deck.json hold_maker")
            except (FileNotFoundError, KeyError):
                print("check SKIPPED: no deck.json hold_maker (run extract.py first)")
        print(f"[{set_name}] lb={lb:2d}  unit SR {row['unit']['sharpe']:.2f}  prod SR {row['prod']['sharpe']:.2f}"
              f"  prod MDD {row['prod']['mdd']:.1%}  CAGR {row['prod']['cagr']:.1%}  tr/wk {row['trades_per_week']:.1f}"
              f"  net {row['net_bp']:.1f}bp  stop {row['stop_share']:.0%}"
              f"  | vs14 unit t {row['diff_unit']['t']:.2f} prod t {row['diff_prod']['t']:.2f}"
              f" corr {row['diff_prod']['corr']:.2f}")
        print("      yearly unit SR", row["yearly_unit"], " per-year prod t", row["diff_prod"]["per_year_t"])
json.dump(res, open(f"{OUT}/lookback.json", "w"), default=str, indent=1)
print("written", f"{OUT}/lookback.json")
