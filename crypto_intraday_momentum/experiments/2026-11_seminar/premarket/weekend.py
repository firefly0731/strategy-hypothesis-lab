"""Noise-band momentum on crypto WEEKEND days (Sat, Sun), 24h UTC sessions, 2021-01..2026-10.
Adopted rules scaled to the session: cutoff at 69% of the session (270/390), VWAP 0.6 sigma,
maker_chase execution, rv sizing as in the backtest. Weekdays (same 24h UTC spec) and the
US-hours production spec shown for comparison. Pass: weekend t >= 2.5 discovery, same sign t >= 1.5 hold-out."""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from crypto_intraday_momentum.backtest import Config, run_backtest
from crypto_intraday_momentum.cpcv import EXEC
from crypto_intraday_momentum.data import load_funding, load_klines
from crypto_intraday_momentum.run import TICKS
from crypto_intraday_momentum.sessions import US, UTC, build_sessions
from crypto_intraday_momentum.signals import compute_signals

SETS = {"discovery": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "holdout": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}
for setname, syms in SETS.items():
    T = []
    for sym in syms:
        df = load_klines(sym, "2021-01", "2026-10"); fund = load_funding(sym, "2021-01", "2026-10")
        for spec, cutoff in ((UTC, int(1440 * 270 / 390)), (US, 270)):
            m = build_sessions(df, spec); s = compute_signals(m, interval=30)
            cfg = Config(tick=TICKS.get(sym, 0.01), entry_cutoff_min=cutoff, vwap_confirm_k=0.6, **EXEC["maker_chase"])
            t = run_backtest(m, s, cfg, fund).trades.copy()
            t["sym"], t["spec"] = sym, spec.name
            t["net_bps"] = t["ret_notional"] * 1e4
            T.append(t)
    T = pd.concat(T); T["wd"] = pd.to_datetime(T["date"]).dt.weekday
    T["grp"] = np.where(T.spec == "us", "US hours (production)", np.where(T.wd >= 5, "UTC weekend", "UTC weekday"))
    print(f"\n{setname}")
    for g, x in T.groupby("grp"):
        day = x.groupby("date").ret_equity.sum()
        yr = x.groupby(pd.to_datetime(x.date).dt.year).net_bps.mean().round(1).to_dict()
        print(f"  {g:22s} trades {len(x):5d} net {x.net_bps.mean():+6.1f} bp/trade  t {x.net_bps.mean()/x.net_bps.std()*np.sqrt(len(x)):+.2f}"
              f"  day-Sharpe {day.mean()/day.std()*np.sqrt(252):+.2f}  bp/trade by year {yr}")
