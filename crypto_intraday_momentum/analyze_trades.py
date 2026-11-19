"""Trade attribution: performance by decision time and by entry-time features.

All features are computed from information available at the decision time
(bars < m of the current session, previous sessions).

    python -m crypto_intraday_momentum.analyze_trades --symbols BTCUSDT ETHUSDT SOLUSDT
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Config, run_backtest
from .cpcv import EXEC
from .data import load_funding, load_klines
from .run import TICKS
from .sessions import US, build_sessions
from .signals import _rolling_prior_mean, compute_signals

OUT = Path(__file__).parent / "results" / "attribution"


def entry_features(m, s, t: pd.DataFrame, lookback: int = 14) -> pd.DataFrame:
    i, j, side = t["sess_idx"].to_numpy(), t["dec_j"].to_numpy(), t["side"].to_numpy()
    sig = s.sigma[i, j]
    p = s.px[i, j]
    band = np.where(side > 0, s.ub[i, j], s.lb[i, j])
    prev_px = np.where(j > 0, s.px[i, np.maximum(j - 1, 0)], s.sess_open[i])
    cv = np.cumsum(m.V, axis=1)[:, s.dec_min - 1]
    relvol = cv / _rolling_prior_mean(cv, lookback)
    gap = s.sess_open / s.prev_close - 1.0
    f = pd.DataFrame({
        "excess_sigma": side * (p / band - 1.0) / sig,           # how far beyond the band
        "move_from_open_sigma": side * (p / s.sess_open[i] - 1.0) / sig,
        "last_interval_move_sigma": side * (p / prev_px - 1.0) / sig,
        "vwap_dist_sigma": side * (p / s.vwap[i, j] - 1.0) / sig,
        "rel_volume": relvol[i, j],
        "gap_with_side_vol": side * gap[i] / s.daily_vol[i],
        "abs_gap_vol": np.abs(gap[i]) / s.daily_vol[i],
        "sigma_bps": sig * 1e4,
        "daily_vol_bps": s.daily_vol[i] * 1e4,
    }, index=t.index)
    # "what if we just held to the close" on the same entry
    f["hold_to_close_gross_bps"] = side * (m.C[i, -1] / t["entry_px"].to_numpy() - 1.0) * 1e4
    return f


def _bucket_table(df, key, val="net_bps", q=None, labels=None):
    g = df.groupby(pd.qcut(df[key], q, duplicates="drop") if q else df[key], observed=True)
    out = pd.DataFrame({
        "n": g.size(),
        "net_bps": g[val].mean(),
        "t": g[val].mean() / g[val].std(ddof=1) * np.sqrt(g.size()),
        "gross_bps": g["gross_bps"].mean(),
        "win%": g["net_bps"].apply(lambda x: (x > 0).mean() * 100),
        "pnl_share%": g["ret_equity"].sum() / df["ret_equity"].sum() * 100,
    })
    return out


def run(symbols, start, end, exec_name="maker_chase", interval=30):
    frames = []
    for sym in symbols:
        df = load_klines(sym, start, end)
        fund = load_funding(sym, start, end)
        m = build_sessions(df, US)
        s = compute_signals(m, interval=interval)
        res = run_backtest(m, s, Config(tick=TICKS.get(sym, 0.01), **EXEC[exec_name]), fund)
        t = res.trades.copy()
        t["symbol"] = sym
        t["net_bps"] = t["ret_notional"] * 1e4
        t["gross_bps"] = t["gross"] / t["notional"] * 1e4
        t["cost_bps"] = (t["fees"] + t["funding"]) / t["notional"] * 1e4
        t = pd.concat([t, entry_features(m, s, t)], axis=1)
        t["hold_to_close_net_bps"] = t["hold_to_close_gross_bps"] - t["cost_bps"]
        t["time"] = (pd.Timestamp("2000-01-01 09:30") + pd.to_timedelta(t["dec_min"], "min")).dt.strftime("%H:%M")
        frames.append(t)
    return pd.concat(frames, ignore_index=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--exec", default="maker_chase", choices=list(EXEC))
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    T = run(a.symbols, a.start, a.end, a.exec)
    T.to_parquet(OUT / "trades_with_features.parquet")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    lines = []

    def show(title, tab):
        txt = f"\n### {title}\n" + tab.round(2).to_string()
        print(txt); lines.append(txt)

    by_t = _bucket_table(T, "time")
    by_t["hold_to_close_net_bps"] = T.groupby("time")["hold_to_close_net_bps"].mean()
    by_t["avg_hold_min"] = T.groupby("time")["hold_min"].mean()
    by_t["eod_exit%"] = T.groupby("time")["exit_reason"].apply(lambda x: (x == "eod").mean() * 100)
    show("by decision time (pooled)", by_t)
    show("net bps by decision time x symbol",
         T.pivot_table(index="time", columns="symbol", values="net_bps", aggfunc="mean"))
    show("by entry kind", _bucket_table(T, "entry_kind"))
    show("by exit reason", _bucket_table(T, "exit_reason"))
    T["side_lbl"] = np.where(T["side"] > 0, "long", "short")
    show("by side", _bucket_table(T, "side_lbl"))
    for k in ["excess_sigma", "move_from_open_sigma", "last_interval_move_sigma", "vwap_dist_sigma",
              "rel_volume", "gap_with_side_vol", "abs_gap_vol", "sigma_bps"]:
        show(f"by {k} (quintiles)", _bucket_table(T.dropna(subset=[k]), k, q=5))
    first = T[T["entry_kind"] == "first"]
    T["first_entry_time"] = T["time"].where(T["entry_kind"] == "first")
    sess_first = first.groupby(["symbol", "date"])["time"].first().rename("first_time")
    S = T.merge(sess_first, left_on=["symbol", "date"], right_index=True)
    show("session P&L by time of first entry",
         S.groupby(["first_time"]).agg(n_sessions=("date", lambda x: x.nunique()),
                                       sum_net_bps=("net_bps", "sum")).assign(
             per_session=lambda d: d.sum_net_bps / d.n_sessions))
    (OUT / "attribution_report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
