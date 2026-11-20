"""Noise-band breakouts (crypto_intraday_momentum rules) as an EXIT signal for carry positions.

The band is the one of the adopted momentum strategy (Zarattini, Aziz & Barbon 2024 adaptation):
  O      = open of the session's first bar
  PC     = close of the previous session's last bar
  p(m)   = price at decision minute m = close of the bar ending at m (known at m)
  σ(m)   = mean over the previous 14 sessions of |p(m)/O - 1|   (current session excluded)
  UB(m)  = max(O, PC)·(1 + σ(m)),   LB(m) = min(O, PC)·(1 - σ(m))
Decisions every 30 minutes from session open + 30 min to the last half hour before the close.

30-minute klines reproduce these numbers exactly: the close of the 30m bar [m-30, m) is the
close of the 1m bar starting at m-1, the 30m open at the session start is the 1m open, and the
previous session's last 30m close is its 15:59 (or 23:59) 1m close.

Sessions:
  "us"  NYSE trading days 09:30–16:00 America/New_York, early closes skipped (12 decisions).
  "utc" every UTC day 00:00–24:00 (47 decisions, 00:30 … 23:30).

Use as an exit: a short carry position exits when p(m) > UB(m), a long one when p(m) < LB(m).
`to_bar_grid` maps each event to the first bar close at or after m, and the managed engine
executes on the following bar.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .data import DEFAULT_CACHE, _klines

LOOKBACK = 14
STEP = pd.Timedelta(minutes=30)


def load_30m(symbols, start: str, end: str, cache: Path = DEFAULT_CACHE, workers: int = 8):
    """{symbol: DataFrame(open, close) indexed by 30m bar OPEN time (UTC)}."""
    def one(s):
        k = _klines(s, "30m", start, end, cache)
        if k is None:
            return s, None
        k = k.drop_duplicates("open_time").sort_values("open_time")
        return s, pd.DataFrame({"open": k["open"].to_numpy(), "close": k["close"].to_numpy()},
                               index=pd.DatetimeIndex(k["open_time"]))
    with ThreadPoolExecutor(workers) as ex:
        return {s: d for s, d in ex.map(one, list(symbols)) if d is not None}


def session_starts(kind: str, start, end) -> tuple[pd.DatetimeIndex, int]:
    """(session open times in UTC, number of 30m bars per session)."""
    if kind == "utc":
        lo, hi = (pd.Timestamp(x) for x in (start, end))
        lo = lo.tz_convert("UTC") if lo.tz is not None else lo.tz_localize("UTC")
        hi = hi.tz_convert("UTC") if hi.tz is not None else hi.tz_localize("UTC")
        return pd.date_range(lo.normalize(), hi.normalize(), freq="D"), 48
    if kind != "us":
        raise ValueError("kind must be 'us' or 'utc'")
    from crypto_intraday_momentum.sessions import US, session_dates
    days = session_dates(US, str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date()))
    local = pd.DatetimeIndex(days) + pd.Timedelta(hours=9, minutes=30)
    return local.tz_localize("America/New_York").tz_convert("UTC"), 13


def breakouts(bars30: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Events for one symbol: index = decision time m (UTC), columns up (p > UB), down (p < LB)."""
    if bars30.empty:
        return pd.DataFrame(columns=["up", "down"], dtype=bool)
    starts, nb = session_starts(kind, bars30.index[0], bars30.index[-1])
    o = bars30["open"].reindex(starts).to_numpy()                       # session open
    cl = np.full((len(starts), nb), np.nan)                             # close of bar k of session
    for k in range(nb):
        cl[:, k] = bars30["close"].reindex(starts + k * STEP).to_numpy()
    p = cl[:, :-1]                                                      # decision k+1 uses bar k close
    move = np.abs(p / o[:, None] - 1)
    sig = np.full(move.shape, np.nan)
    for i in range(LOOKBACK, len(starts)):
        w = move[i - LOOKBACK:i]
        ok = np.isfinite(w).all(axis=0)
        sig[i, ok] = w[:, ok].mean(axis=0)
    pc = np.concatenate([[np.nan], cl[:-1, -1]])                        # previous session last close
    hi, lo = np.fmax(o, pc), np.fmin(o, pc)
    with np.errstate(invalid="ignore"):
        ub = np.where(np.isfinite(pc)[:, None], hi[:, None] * (1 + sig), np.nan)
        lb = np.where(np.isfinite(pc)[:, None], lo[:, None] * (1 - sig), np.nan)
        up, down = p > ub, p < lb
    ns = starts.as_unit("ns").asi8[:, None] + np.arange(1, nb)[None, :] * STEP.value   # decision minute m
    t = pd.to_datetime(ns.ravel(), unit="ns", utc=True)
    ev = pd.DataFrame({"up": up.ravel(), "down": down.ravel()}, index=t)
    return ev[ev["up"] | ev["down"]]


def to_bar_grid(events: dict[str, pd.DataFrame], index: pd.DatetimeIndex, symbols) -> tuple[np.ndarray, np.ndarray]:
    """Boolean (bars × symbols) arrays: an event at m is visible at the first bar close ≥ m."""
    up = np.zeros((len(index), len(symbols)), dtype=bool)
    dn = np.zeros_like(up)
    col = {s: i for i, s in enumerate(symbols)}
    for s, ev in events.items():
        if s not in col or ev.empty:
            continue
        j = index.searchsorted(ev.index, side="left")
        keep = j < len(index)
        up[j[keep & ev["up"].to_numpy()], col[s]] = True
        dn[j[keep & ev["down"].to_numpy()], col[s]] = True
    return up, dn


def exit_signals(symbols, start: str, end: str, index: pd.DatetimeIndex, kind: str):
    data = load_30m(symbols, start, end)
    ev = {s: breakouts(d, kind) for s, d in data.items()}
    return to_bar_grid(ev, index, list(symbols))
