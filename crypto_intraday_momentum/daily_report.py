"""Replay the adopted intraday momentum configuration on one NYSE session.

    python -m crypto_intraday_momentum.daily_report --date 2026-11-18

Adopted configuration: US session 09:30-16:00 NY, entry cutoff 14:00, VWAP confirmation 0.6 sigma,
maker_chase execution, rv24 sizing, BTC+ETH+SOL equal weight, 25% portfolio vol target, 3x per-trade
cap, 15% drawdown throttle.

This is a replay on public 1m klines (data.binance.vision), NOT live fills. Funding for months
without a monthly funding archive is unavailable and treated as 0.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .backtest import Config, run_backtest
from .cpcv import EXEC
from .data import load_funding, load_klines
from .run import TICKS
from .run_sizing import build_portfolio
from .sessions import US, build_sessions
from .signals import compute_signals
from .sizing import drawdown_throttle, pre_open_rv, unit_trades

RULES = dict(entry_cutoff_min=270, vwap_confirm_k=0.6)
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def decision_table(m, s, i, trades):
    rows = []
    t_sess = trades[trades["sess_idx"] == i] if len(trades) else trades
    for j, dm in enumerate(s.dec_min):
        t_ny = (m.start_utc[i] + pd.Timedelta(minutes=int(dm))).tz_convert("America/New_York").strftime("%H:%M")
        p, ub, lb, vw, sg = s.px[i, j], s.ub[i, j], s.lb[i, j], s.vwap[i, j], s.sigma[i, j]
        state = "above UB" if p > ub else ("below LB" if p < lb else "inside")
        vw_dist = (p / vw - 1) / sg if sg > 0 else np.nan
        acts = []
        if len(t_sess):
            for _, t in t_sess[t_sess["dec_j"] == j].iterrows():
                acts.append(f"ENTER {'LONG' if t.side > 0 else 'SHORT'} ({'maker' if t.entry_maker else 'taker'})")
            ex = t_sess[((t_sess["exit_time"] - m.start_utc[i]) / pd.Timedelta(minutes=1)).between(dm, dm + 29)
                        & (t_sess["exit_reason"] != "eod")]
            for _, t in ex.iterrows():
                acts.append(f"EXIT {t.exit_reason} ({'maker' if t.exit_maker else 'taker'})")
        rows.append(dict(time_NY=t_ny, price=p, UB=ub, LB=lb, VWAP=vw, sigma_bp=sg * 1e4, state=state,
                         vwap_dist_sigma=vw_dist, action="; ".join(acts)))
    return pd.DataFrame(rows).set_index("time_NY")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="NYSE session date, YYYY-MM-DD")
    ap.add_argument("--history-start", default=None, help="kline history start (default: date - 8 months)")
    a = ap.parse_args(argv)
    day = pd.Timestamp(a.date)
    start = a.history_start or (day - pd.DateOffset(months=8)).strftime("%Y-%m")
    end = day.strftime("%Y-%m")
    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 20)
    data, per_sym = {}, {}
    for sym in SYMS:
        df = load_klines(sym, start, end)
        fund = load_funding(sym, start, end)
        m = build_sessions(df, US)
        if day not in m.dates:
            raise SystemExit(f"{sym}: session {a.date} not available in the kline data "
                             f"(last session {m.dates[-1].date()}) - the archive may not be published yet")
        s = compute_signals(m)
        cfg = Config(tick=TICKS[sym], **EXEC["maker_chase"], **RULES)
        t = unit_trades(m, s, cfg, fund)
        data[sym] = (m, t, pre_open_rv(df, m))
        i = int(np.flatnonzero(m.dates == day)[0])
        per_sym[sym] = (m, s, i, t)
    # portfolio (rv24, equal weight, 25% vol target, 3x cap) + 15% drawdown throttle
    raw, L = build_portfolio(data, "rv24", "equal", 0.25, 3.0)
    thr = drawdown_throttle(raw, 0.15)[0]
    print(f"\n######## Intraday momentum replay — NYSE session {a.date} (09:30–16:00 NY)\n")
    for sym, (m, s, i, t) in per_sym.items():
        ts = t[t["sess_idx"] == i] if len(t) else t
        print(f"=== {sym}  open={m.O[i,0]:.4g}  prev 16:00 close={s.prev_close[i]:.4g}  "
              f"session move={m.C[i,-1]/m.O[i,0]-1:+.2%}  day range={m.H[i].max()/m.L[i].min()-1:.2%}")
        print(decision_table(m, s, i, t).round({"price": 4, "UB": 4, "LB": 4, "VWAP": 4, "sigma_bp": 1,
                                                "vwap_dist_sigma": 2}).to_string())
        if len(ts):
            show = ts[["side", "entry_time", "exit_time", "entry_px", "exit_px", "entry_maker", "exit_maker",
                       "exit_reason", "ret_notional", "mae"]].copy()
            for c in ("entry_time", "exit_time"):
                show[c] = show[c].dt.tz_convert("America/New_York").dt.strftime("%H:%M")
            show["net_bp"] = show.pop("ret_notional") * 1e4
            show["mae_bp"] = show.pop("mae") * 1e4
            print("trades:\n" + show.round(2).to_string(index=False))
        else:
            print("trades: none (no band break passed the filters)")
        print()
    r_raw = raw.get(day, np.nan)
    r_thr = thr.get(day, np.nan)
    hist = thr[thr.index < day]
    eq = (1 + hist).cumprod()
    dd = 1 - eq.iloc[-1] / eq.max() if len(eq) else 0.0
    g = min(1.0, max(0.25, 1 - dd / 0.15))
    print(f"=== portfolio (BTC+ETH+SOL, rv24, 25% vol target)\n"
          f"session return: {r_thr*100:+.3f}% of equity (before throttle {r_raw*100:+.3f}%)\n"
          f"drawdown at prior close: {dd:.2%} -> throttle multiplier {g:.2f}\n"
          f"trailing 20-session mean: {hist.tail(20).mean()*100:+.3f}%/day, "
          f"last 60 sessions cumulative: {(np.prod(1+hist.tail(60))-1)*100:+.2f}%")


if __name__ == "__main__":
    main()
