"""Performance, decomposition and the DTB3 comparison (DESIGN.md §5)."""
from __future__ import annotations

import numpy as np
import pandas as pd

VIDEO_YEARLY = {2019: 0.002, 2020: 0.175, 2021: 0.293, 2022: 0.012, 2023: 0.060, 2024: 0.095,
                2025: 0.034, 2026: 0.012}


def decomposition(bars: pd.DataFrame, initial: float = 1.0) -> dict:
    d = {"funding": bars["funding"].sum(), "basis": (bars["spot_pnl"] + bars["perp_pnl"]).sum(),
         "fees": -bars["fee"].sum(), "slippage": -bars["slippage"].sum(), "liq_loss": -bars["liq_loss"].sum()}
    d["total"] = sum(d.values())
    eq = bars["equity"].iloc[-1] - initial
    assert abs(d["total"] - eq) <= 1e-9 * max(1.0, abs(eq)), (d["total"], eq)
    return d


def performance(bars: pd.DataFrame, initial: float = 1.0) -> dict:
    eq = bars["equity"]
    daily = pd.concat([pd.Series([initial], index=[eq.index[0] - pd.Timedelta(hours=1)]), eq])
    daily = daily.resample("1D").last().dropna()
    r = daily.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0] + pd.Timedelta(hours=1)).total_seconds() / (365.25 * 86400)
    total = eq.iloc[-1] / initial - 1
    down = r[r < 0]
    return {"total_return": total, "cagr": (1 + total) ** (1 / years) - 1 if total > -1 else -1.0,
            "mdd": float((eq / np.maximum.accumulate(np.r_[initial, eq.to_numpy()])[1:] - 1).min()),
            "vol": r.std() * np.sqrt(365),
            "sharpe": r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan,
            "sortino": r.mean() / np.sqrt((down ** 2).sum() / len(r)) * np.sqrt(365) if len(down) else np.nan,
            "rebalances": int(bars["n_rebal"].sum()), "liquidations": int(bars["n_liq"].sum()),
            "entries": int(bars["n_entries"].sum()), "exits": int(bars["n_exits"].sum()),
            "fees": bars["fee"].sum(), "slippage": bars["slippage"].sum(),
            "turnover_per_year": bars["traded"].sum() / years / initial, "years": years}


def yearly(bars: pd.DataFrame, initial: float = 1.0) -> pd.DataFrame:
    eq = bars["equity"]
    prev = pd.concat([pd.Series([initial], index=[eq.index[0] - pd.Timedelta(hours=1)]), eq])
    out = []
    # a bar closing at 00:00 ends the previous day (DESIGN.md §4.A), so group by close − 1h
    for y, g in eq.groupby((eq.index - pd.Timedelta(hours=1)).year):
        start = prev[prev.index < g.index[0]].iloc[-1]
        b = bars.loc[g.index]
        out.append({"year": y, "return": g.iloc[-1] / start - 1,
                    "funding": b["funding"].sum() / start, "basis": (b["spot_pnl"] + b["perp_pnl"]).sum() / start,
                    "costs": -(b["fee"] + b["slippage"] + b["liq_loss"]).sum() / start,
                    "mdd": float((g / np.maximum.accumulate(np.r_[start, g.to_numpy()])[1:] - 1).min()),
                    "from": g.index[0] - pd.Timedelta(hours=1), "to": g.index[-1]})
    return pd.DataFrame(out).set_index("year")


def tbill_yearly(dtb3: pd.Series, windows: pd.DataFrame) -> pd.DataFrame:
    """For each strategy year window: average DTB3 (%) and the return of accruing r/100/365 per calendar day."""
    days = pd.date_range(dtb3.index.min(), max(dtb3.index.max(), windows["to"].max().normalize()), freq="D", tz="UTC")
    rate = dtb3.reindex(days).ffill()
    out = []
    for y, w in windows.iterrows():
        d = rate[(rate.index >= w["from"]) & (rate.index < w["to"])]       # calendar days in [from, to)
        out.append({"year": y, "tbill_avg_pct": d.mean(), "tbill_return": float(np.prod(1 + d / 100 / 365) - 1)})
    return pd.DataFrame(out).set_index("year")
