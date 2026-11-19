"""Noise band / VWAP signals (Zarattini, Aziz & Barbon 2024), look-ahead safe.

Timing convention — the whole point of this module:

    decision minute m  (e.g. m = 30  ->  10:00 NY in US mode)
    information set    = bars 0 .. m-1 of the session (all CLOSED by minute m)
    price at decision  = close of bar m-1 (open_time = start + m - 1 min)
    first executable   = bar m (open_time = start + m min)

So the 10:00 decision uses the 09:59 bar's close and can only trade from the
10:00 bar onward. Nothing at index >= m of the current session, and nothing
from future sessions, enters any array below.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .sessions import SessionMatrix


@dataclass
class Signals:
    dec_min: np.ndarray    # (n_dec,) decision minutes since session start
    px: np.ndarray         # (n, n_dec) last closed price at decision
    ub: np.ndarray         # upper band
    lb: np.ndarray         # lower band
    vwap: np.ndarray       # session VWAP over bars 0..m-1
    sigma: np.ndarray      # noise (avg |move from open|) from prior sessions
    sess_open: np.ndarray  # (n,)
    prev_close: np.ndarray # (n,)
    daily_vol: np.ndarray  # (n,) std of prior session close-to-close returns


def decision_minutes(n_minutes: int, interval: int = 30, first: int = 30) -> np.ndarray:
    return np.arange(first, n_minutes, interval)


def _rolling_prior_mean(x: np.ndarray, lookback: int) -> np.ndarray:
    """out[i] = mean(x[i-lookback : i]) along axis 0; NaN if not enough history."""
    out = np.full(x.shape, np.nan)
    cs = np.cumsum(np.nan_to_num(x), axis=0)
    cs = np.concatenate([np.zeros((1,) + x.shape[1:]), cs], axis=0)
    cnt = np.cumsum(~np.isnan(x), axis=0)
    cnt = np.concatenate([np.zeros((1,) + x.shape[1:]), cnt], axis=0)
    i = np.arange(lookback, x.shape[0])
    s = cs[i] - cs[i - lookback]
    c = cnt[i] - cnt[i - lookback]
    with np.errstate(invalid="ignore"):
        out[lookback:] = np.where(c == lookback, s / np.maximum(c, 1), np.nan)
    return out


def compute_signals(m: SessionMatrix, lookback: int = 14, interval: int = 30,
                    first: int = 30, vol_lookback: int = 14,
                    ref_close_min: int | None = None) -> Signals:
    """ref_close_min: minute of the reference close used for prev_close / daily vol
    (defaults to the session end). Set it to 390 when sessions are extended past
    16:00 NY so that the entry signal is unchanged."""
    dm = decision_minutes(m.C.shape[1], interval, first)
    sess_open = m.O[:, 0]
    px = m.C[:, dm - 1]                                     # close of bar m-1

    move = np.abs(px / sess_open[:, None] - 1.0)
    sigma = _rolling_prior_mean(move, lookback)              # prior sessions only

    sess_close = m.C[:, (ref_close_min or m.C.shape[1]) - 1]
    prev_close = np.concatenate([[np.nan], sess_close[:-1]])
    hi_ref = np.fmax(sess_open, prev_close)
    lo_ref = np.fmin(sess_open, prev_close)
    ub = hi_ref[:, None] * (1.0 + sigma)
    lb = lo_ref[:, None] * (1.0 - sigma)

    cqv = np.cumsum(m.QV, axis=1)[:, dm - 1]
    cv = np.cumsum(m.V, axis=1)[:, dm - 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.where(cv > 0, cqv / cv, px)

    ret = sess_close / prev_close - 1.0                      # known at session end
    r2 = np.stack([ret, ret ** 2], axis=1)
    mu = _rolling_prior_mean(r2, vol_lookback)               # uses sessions < i
    daily_vol = np.sqrt(np.maximum(mu[:, 1] - mu[:, 0] ** 2, 0.0)
                        * vol_lookback / max(vol_lookback - 1, 1))

    return Signals(dm, px, ub, lb, vwap, sigma, sess_open, prev_close, daily_vol)
