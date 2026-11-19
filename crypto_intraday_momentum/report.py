"""Performance statistics and robustness checks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import Result


def summarize(res: Result, periods_per_year: float) -> dict:
    t, s = res.trades, res.sessions
    act = s[s["active"]]
    out = {"sessions": int(len(act)), "trades": int(len(t))}
    if len(act) == 0:
        return out
    eq = s["equity_end"].to_numpy()
    eq0 = res.config.initial_equity
    years = len(act) / periods_per_year
    peak = np.maximum.accumulate(np.concatenate([[eq0], eq]))
    dd = np.concatenate([[eq0], eq]) / peak - 1.0
    r = act["ret"].to_numpy()
    out.update(
        total_return=eq[-1] / eq0 - 1.0,
        cagr=(eq[-1] / eq0) ** (1 / years) - 1.0 if years > 0 and eq[-1] > 0 else np.nan,
        sharpe=r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year) if r.std() > 0 else np.nan,
        max_drawdown=dd.min(),
    )
    if len(t):
        rn = t["ret_notional"].to_numpy()
        out.update(
            win_rate=float((t["pnl"] > 0).mean()),
            avg_bps_per_trade=rn.mean() * 1e4,
            t_stat=rn.mean() / rn.std(ddof=1) * np.sqrt(len(rn)) if len(rn) > 1 else np.nan,
            avg_hold_min=float(t["hold_min"].mean()),
            maker_entry_share=float(t["entry_maker"].mean()),
            maker_exit_share=float(t["exit_maker"].mean()),
            fees_pct_equity=float((t["fees"] / t["notional"]).mean() * 1e4),
            funding_total=float(t["funding"].sum()),
            long_share=float((t["side"] > 0).mean()),
        )
        top = act.sort_values("ret", ascending=False)
        ex10 = np.prod(1 + act.loc[~act.index.isin(top.index[:10]), "ret"]) - 1
        out["total_return_ex_top10_days"] = ex10
    out["missed_entries"] = int(len(res.missed))
    if len(res.missed):
        out["missed_avg_move_to_close_bps"] = float(res.missed["move_to_close"].mean() * 1e4)
    return out


def yearly(res: Result) -> pd.DataFrame:
    s = res.sessions[res.sessions["active"]].copy()
    s["year"] = pd.DatetimeIndex(s["date"]).year
    g = s.groupby("year")
    out = pd.DataFrame({"ret": g["ret"].apply(lambda x: np.prod(1 + x) - 1),
                        "trades": g["n_trades"].sum()})
    if len(res.trades):
        tt = res.trades.copy()
        tt["year"] = pd.DatetimeIndex(tt["date"]).year
        out["avg_bps"] = tt.groupby("year")["ret_notional"].mean() * 1e4
    return out


def random_direction_test(res: Result, n: int = 1000, seed: int = 0) -> dict:
    """Keep entry/exit times and costs, randomise long/short. Approximate:
    fills are taken as-is, so use it on taker runs. Returns the share of
    random runs whose mean per-trade return >= the real one."""
    t = res.trades
    if len(t) < 2:
        return {}
    gross = (t["exit_px"] / t["entry_px"] - 1.0).to_numpy()       # long-side move
    cost = (t["fees"] / t["notional"]).to_numpy()
    real = t["ret_notional"].mean()
    rng = np.random.default_rng(seed)
    sides = rng.choice([-1.0, 1.0], size=(n, len(t)))
    sims = (sides * gross - cost).mean(axis=1)
    return {"real_bps": real * 1e4, "random_mean_bps": sims.mean() * 1e4,
            "p_value": float((sims >= real).mean())}
