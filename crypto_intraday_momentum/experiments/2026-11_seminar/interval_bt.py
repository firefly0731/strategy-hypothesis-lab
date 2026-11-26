"""Decision interval 30 / 15 / 5 min with the production rules (14:00 cutoff, VWAP 0.6 sigma),
maker_chase, BTC+ETH+SOL. Reports 1x unit basket and production-sized portfolio."""
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
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
VARIANTS = {"30m": (30, 30), "15m": (15, 30), "15m_from15": (15, 15), "5m": (5, 30), "5m_from5": (5, 5)}


def mt(r):
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1
    return dict(cagr=eq.iloc[-1] ** (PPY / len(r)) - 1, vol=r.std() * np.sqrt(PPY),
                sharpe=r.mean() / r.std() * np.sqrt(PPY), mdd=dd.min())


if len(sys.argv) > 2:                      # stage: one symbol per process
    sym = sys.argv[2]
    df = load_klines(sym, "2021-01", "2026-10"); fund = load_funding(sym, "2021-01", "2026-10")
    m = build_sessions(df, US); rv = pre_open_rv(df, m)
    cfg = Config(tick=TICKS.get(sym, 0.01), **EXEC["maker_chase"], **RULES)
    out = {}
    for k, (iv, first) in VARIANTS.items():
        s = compute_signals(m, interval=iv, first=first)
        out[k] = unit_trades(m, s, cfg, fund)
    pd.to_pickle(dict(m=m, rv=rv, t=out), f"{OUT}/IV_{sym}.pkl"); print("saved", sym); sys.exit(0)

D = {s: pd.read_pickle(f"{OUT}/IV_{s}.pkl") for s in SYMS}
res = {}
for k in VARIANTS:
    data = {s: (D[s]["m"], D[s]["t"][k], D[s]["rv"]) for s in SYMS}
    T = pd.concat([t.assign(sym=s) for s, (_, t, _) in data.items()])
    # 1x unit basket: per-session sum of ret_notional per coin, equal weight
    m0 = D[SYMS[0]]["m"]
    U = pd.DataFrame({s: t.groupby("sess_idx").ret_notional.sum().reindex(range(D[s]["m"].n)).fillna(0.0)
                      .set_axis(D[s]["m"].dates) for s, (_, t, _) in data.items()}).fillna(0.0).iloc[31 + 60:]
    u = U.mean(axis=1)
    r, L = build_portfolio(data, "rv24", "equal", 0.25, 3.0, 0.15, scale_cap=20.0)
    r = r.iloc[60:]
    weeks = len(u) / PPY * 52
    res[k] = dict(unit=mt(u), prod=mt(r), trades_per_week=len(T[T.date >= u.index[0]]) / weeks,
                  net_bp=T.ret_notional.mean() * 1e4, gross_bp=(T.gross / T.notional).mean() * 1e4,
                  fee_bp=(T.fees / T.notional).mean() * 1e4, win=(T.pnl > 0).mean(),
                  hold_min=T.hold_min.mean(), maker_entry=T.entry_maker.mean(), n=len(T),
                  stop_share=(T.exit_reason == "stop").mean(),
                  yearly_unit=u.groupby(u.index.year).apply(lambda x: x.mean() / x.std() * np.sqrt(PPY)).round(2).to_dict(),
                  span=[str(u.index[0].date()), str(u.index[-1].date())])
    print(k, {a: (round(b, 3) if isinstance(b, float) else b) for a, b in res[k].items() if a not in ("unit", "prod", "yearly_unit")})
    print("   unit", {a: round(b, 3) for a, b in res[k]["unit"].items()}, " prod", {a: round(b, 3) for a, b in res[k]["prod"].items()})
    print("   yearly unit SR", res[k]["yearly_unit"])
json.dump(res, open(f"{OUT}/interval.json", "w"), default=str, indent=1)
