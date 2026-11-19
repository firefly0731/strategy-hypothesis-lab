"""Position sizing research for the intraday momentum strategy.

P&L is linear in position size (no market-impact model), so the strategy is run
once at 1x notional. Every sizing scheme then assigns a leverage L_t to each
trade:

    trade return on equity = L_t * ret_notional_t
    session return         = sum over the session's trades of L_t * ret_notional_t

Look-ahead rule: L_t may only use information known at the trade's decision time.
That means previous sessions, the decision-time band / VWAP / sigma, and the
strategy's own past returns.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Config, run_backtest
from .sessions import SessionMatrix
from .signals import Signals


# ----------------------------------------------------------------------------- unit trades

def unit_trades(m: SessionMatrix, s: Signals, cfg: Config, funding=None) -> pd.DataFrame:
    """Trades at fixed 1x notional, with sizing features known at decision time."""
    cfg = Config(**{**cfg.to_dict(), "sizing": "fixed", "fixed_leverage": 1.0})
    t = run_backtest(m, s, cfg, funding).trades.copy()
    if t.empty:
        return t
    i, j, side = t["sess_idx"].to_numpy(), t["dec_j"].to_numpy(), t["side"].to_numpy()
    p = s.px[i, j]
    stop = np.where(side > 0, np.maximum(s.ub[i, j], s.vwap[i, j]), np.minimum(s.lb[i, j], s.vwap[i, j]))
    t["stop_dist"] = side * (p - stop) / p                  # distance to the trailing stop
    t["sigma"] = s.sigma[i, j]
    t["daily_vol"] = s.daily_vol[i]
    # max adverse excursion (fraction of entry) while the trade was open
    start = m.start_utc[i]
    eb = ((t["entry_time"] - start) // pd.Timedelta(minutes=1)).to_numpy().astype(int)
    xb = ((t["exit_time"] - start) // pd.Timedelta(minutes=1)).to_numpy().astype(int)
    mae = np.empty(len(t))
    for n_, (ii, a, b, sd, ep) in enumerate(zip(i, eb, xb, side, t["entry_px"].to_numpy())):
        if sd > 0:
            mae[n_] = m.L[ii, a:b + 1].min() / ep - 1.0
        else:
            mae[n_] = 1.0 - m.H[ii, a:b + 1].max() / ep
    t["mae"] = mae
    return t


def pre_open_rv(df: pd.DataFrame, m: SessionMatrix, hours: int = 24) -> np.ndarray:
    """Realised daily vol from 5-minute returns over the `hours` before each open
    (crypto trades 24/7, so this uses the whole day before the session)."""
    c = df["close"]
    idx0 = df.index[0]
    out = np.full(m.n, np.nan)
    arr = c.to_numpy()
    n_bars = hours * 60
    for i, st in enumerate(m.start_utc):
        k = int((st - idx0) // pd.Timedelta(minutes=1))
        if k - n_bars < 0:
            continue
        w = arr[k - n_bars:k][4::5]
        r = np.diff(np.log(w))
        out[i] = np.sqrt((r ** 2).sum() * 24 / hours)       # scale to 1 day
    return out


# ----------------------------------------------------------------------------- schemes

@dataclass
class SchemeResult:
    name: str
    sess_ret: pd.Series      # per-session return on the symbol's allocated equity
    lev: pd.Series           # per-trade leverage


def _ewma_prior(x: np.ndarray, halflife: float) -> np.ndarray:
    """EWMA of x[0..i-1] for each i (strictly prior). NaN for i = 0."""
    s = pd.Series(x).ewm(halflife=halflife, min_periods=5).mean().shift(1)
    return s.to_numpy()


def session_unit_returns(t: pd.DataFrame, n_sess: int) -> np.ndarray:
    u = np.zeros(n_sess)
    np.add.at(u, t["sess_idx"].to_numpy(), t["ret_notional"].to_numpy())
    return u


def apply_scheme(t: pd.DataFrame, m: SessionMatrix, name: str, *, cap: float = 4.0,
                 target: float = 0.02, rv24: np.ndarray | None = None,
                 strat_lookback: int = 60, risk_per_trade: float = 0.005,
                 dist_floor_sigma: float = 0.5, dd_max: float | None = None,
                 dd_floor: float = 0.25) -> SchemeResult:
    """Per-trade leverage for one symbol. Leverage uses only information known before
    the trade's decision time."""
    i = t["sess_idx"].to_numpy()
    n = m.n
    if name == "paper":                                  # min(4, 2% / 14d close-close vol)
        lev = np.minimum(cap, target / t["daily_vol"].to_numpy())
    elif name == "rv24":                                 # 24h pre-open realised vol
        lev = np.minimum(cap, target / rv24[i])
    elif name == "ewma_rv24":                            # smoothed 24h realised vol
        v = np.sqrt(_ewma_prior(rv24 ** 2, 5))            # sessions < i
        v = np.where(np.isfinite(v), v, rv24)             # warm-up fallback
        # combine: today's pre-open RV is known at the open, so blend it in
        lev = np.minimum(cap, target / np.sqrt(0.5 * v[i] ** 2 + 0.5 * rv24[i] ** 2))
    elif name == "strategy_vol":                         # target the strategy's own vol
        u = session_unit_returns(t, n)
        sd = pd.Series(u).rolling(strat_lookback, min_periods=20).std().shift(1).to_numpy()
        lev = np.minimum(cap, (target / 4) / sd[i])       # ~0.5% daily strategy vol per symbol
    elif name == "risk_per_trade":                       # lose ~R of equity if stopped
        dist = np.maximum(t["stop_dist"].to_numpy(), dist_floor_sigma * t["sigma"].to_numpy())
        lev = np.minimum(cap, risk_per_trade / dist)
    else:
        raise ValueError(name)
    lev = np.where(np.isfinite(lev), lev, 0.0)
    sess = np.zeros(n)
    np.add.at(sess, i, lev * t["ret_notional"].to_numpy())
    r = pd.Series(sess, index=m.dates)
    levs = pd.Series(lev, index=t.index)
    if dd_max is not None:                               # drawdown throttle (causal)
        r, mult = drawdown_throttle(r, dd_max, dd_floor)
        levs = levs * mult[i]
    return SchemeResult(name + ("" if dd_max is None else f"+dd{dd_max:g}"), r, levs)


def drawdown_throttle(r: pd.Series, dd_max: float, floor: float = 0.25):
    """Scale session i by g = clip(1 - DD_{i-1}/dd_max, floor, 1), where DD is the
    throttled equity's drawdown at the end of session i-1."""
    x = r.to_numpy()
    out = np.empty_like(x)
    g = np.empty_like(x)
    eq = peak = 1.0
    for k in range(len(x)):
        dd = 1 - eq / peak
        g[k] = min(1.0, max(floor, 1 - dd / dd_max))
        out[k] = g[k] * x[k]
        eq *= 1 + out[k]
        peak = max(peak, eq)
    return pd.Series(out, index=r.index), g


# ----------------------------------------------------------------------------- portfolio

def combine(series: dict[str, pd.Series], method: str = "equal", lookback: int = 60) -> pd.Series:
    """Combine per-symbol session returns. Weights come from data before session i."""
    R = pd.DataFrame(series).fillna(0.0)
    if method == "equal":
        w = pd.DataFrame(1.0 / R.shape[1], index=R.index, columns=R.columns)
    elif method == "inv_vol":
        sd = R.rolling(lookback, min_periods=20).std().shift(1)
        iv = 1.0 / sd
        w = iv.div(iv.sum(axis=1), axis=0).fillna(1.0 / R.shape[1])
    else:
        raise ValueError(method)
    return (w * R).sum(axis=1)


def metrics(r: pd.Series, ppy: float = 252) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    yrs = len(r) / ppy
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else np.nan
    vol = r.std(ddof=1) * np.sqrt(ppy)
    under = (dd < 0).astype(int)
    longest = (under.groupby((under == 0).cumsum()).cumsum()).max()
    return dict(sharpe=r.mean() / r.std(ddof=1) * np.sqrt(ppy), cagr=cagr, vol=vol,
                mdd=dd.min(), calmar=cagr / -dd.min() if dd.min() < 0 else np.nan,
                worst_day=r.min(), longest_dd_sessions=int(longest),
                t=r.mean() / r.std(ddof=1) * np.sqrt(len(r)))
