"""Per-session sizing multipliers, computed before the open from earlier sessions only.

Reproduces crypto_intraday_momentum.run_sizing.build_portfolio + sizing.drawdown_throttle
for the adopted scheme (rv24, equal weight, 25% vol target, scale cap 20, 3x cap, dd 15%):

    lev_sym      = target_daily / RV24_sym               (RV24: 5-min returns, 24h before the open)
    raw_k        = sum_sym W * lev_sym,k * unit_return_sym,k   (unscaled portfolio, sessions k < D)
    scale_D      = min(cap, target_ann / (std(raw over the last 60 sessions) * sqrt(252)))
                   0 while fewer than 20 sessions are available
    eff_sym      = min(max_lev, lev_sym * W * scale_D)   per-trade leverage on total equity
    g_D          = clip(1 - DD_{D-1} / dd_max, floor, 1) DD of the throttled curve at the prior close
    order size   = equity * g_D * eff_sym / price

The throttle uses the BACKTEST-REPLAYED equity curve from HISTORY_START, as in the research
code; it is path dependent, so the history anchor is part of the specification.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_intraday_momentum.run_sizing import build_portfolio
from crypto_intraday_momentum.sizing import apply_scheme, drawdown_throttle

from .strategy import SizingParams


@dataclass(frozen=True)
class SessionSizing:
    date: pd.Timestamp
    scale: float
    weight: float
    g: float                       # drawdown throttle multiplier
    dd: float                      # drawdown at the prior close
    lev: dict                      # per symbol 2% / RV24 (before weights)
    eff: dict                      # per symbol min(max_lev, lev * W * scale)

    def multiplier(self, sym: str) -> float:
        """Notional / total equity for a trade in `sym` this session."""
        return self.g * self.eff[sym]


def _before(t: pd.DataFrame, m, day) -> pd.DataFrame:
    if t.empty:
        return t
    d = pd.DatetimeIndex(m.dates[t["sess_idx"].to_numpy()])
    return t[np.asarray(d < day)]


def session_sizing(data: dict, day, p: SizingParams = SizingParams()) -> SessionSizing:
    """data: {sym: (SessionMatrix, unit trades, rv24 per session)} with session `day` in each
    matrix (its rv24 is known at the open). Trades on or after `day` are ignored."""
    if p.scheme != "rv24":
        raise ValueError("only the adopted rv24 scheme is implemented")
    day = pd.Timestamp(day)
    past = {s: (m, _before(t, m, day), rv) for s, (m, t, rv) in data.items()}

    # unscaled portfolio returns of earlier sessions (same construction as build_portfolio)
    per_sym = {s: apply_scheme(t, m, "rv24", cap=1e9, rv24=rv).sess_ret for s, (m, t, rv) in past.items()}
    R = pd.DataFrame(per_sym).fillna(0.0).iloc[p.warmup:]
    w = 1.0 / R.shape[1]
    hist = R[R.index < day]
    if day not in R.index:
        raise ValueError(f"{day.date()} is not a session after the warm-up in the data")
    raw = (w * hist).sum(axis=1).tail(p.vol_lookback)
    if len(raw) < p.vol_min_periods:
        scale = 0.0
    else:
        vol = raw.std(ddof=1) * np.sqrt(p.ppy)
        scale = p.scale_cap if vol == 0 else min(p.scale_cap, p.target_ann / vol)

    lev, eff = {}, {}
    for s, (m, _, rv) in past.items():
        i = int(np.flatnonzero(m.dates == day)[0])
        x = p.target_daily / rv[i]
        lev[s] = float(x) if np.isfinite(x) else 0.0
        eff[s] = float(min(p.max_lev, lev[s] * w * scale))

    # drawdown of the throttled portfolio at the prior close
    out, _ = build_portfolio(past, "rv24", "equal", p.target_ann, p.max_lev,
                             vol_lookback=p.vol_lookback, scale_cap=p.scale_cap)
    # g for `day` is exactly what drawdown_throttle assigns to that session: run it over the
    # earlier sessions plus a placeholder for `day` (its return does not affect its own g)
    prior = out[out.index < day]
    path = pd.concat([prior, pd.Series([0.0], index=[day])])
    thr, gs = drawdown_throttle(path, p.dd_max, p.dd_floor)
    g = float(gs[-1])
    eq = np.concatenate([[1.0], np.cumprod(1 + thr.to_numpy()[:-1])])
    dd = float(1 - eq[-1] / eq.max())
    return SessionSizing(day, float(scale), w, g, dd, lev, eff)
