"""Markov-chain Monte-Carlo noise bands.

The paper's band is sigma(m) = mean |price(m)/open - 1| over the previous 14
sessions. Here the band is the q / (1-q) quantile of the cumulative return
from the open to minute m, simulated under a "noise" model:

  1. 5-minute log returns inside the session, standardised by a time-of-day
     scale s_k (RMS of slot k over the lookback sessions). This removes the
     intraday seasonality.
  2. A discrete Markov chain on volatility states. |z| is cut into n_states
     quantile buckets. The transition matrix is counted from consecutive slots
     (never across sessions) with Laplace smoothing.
  3. The starting state comes from the realised vol of the 60 minutes BEFORE the
     open, ranked against the same quantity in the lookback sessions.
  4. Each path step draws the next state from P[state], then draws a z from the
     empirical pool of that state (bootstrap: fat tails and skew are kept),
     and adds s_k * z.

Look-ahead: everything for session i uses sessions i-L..i-1 plus the pre-open
bars of session i, which are all closed at the open. The RNG is seeded per
session, so the draws for session i do not depend on any other session.
n_states = 1 is the control: the same time-of-day bootstrap, but with no Markov structure.
"""
from __future__ import annotations

import numpy as np

from .sessions import SessionMatrix
from .signals import Signals, compute_signals

STEP = 5


def _five_min_returns(m: SessionMatrix) -> np.ndarray:
    c = m.C[:, STEP - 1::STEP]
    prev = np.concatenate([m.O[:, :1], c[:, :-1]], axis=1)
    return np.log(c / prev)


def _pre_open_rv(m: SessionMatrix) -> np.ndarray:
    if m.pre_C is None:
        return np.full(m.n, np.nan)
    c = m.pre_C[:, STEP - 1::STEP]
    r = np.diff(np.log(c), axis=1)
    return np.sqrt((r ** 2).mean(axis=1))


def mc_quantiles(m: SessionMatrix, dec_min: np.ndarray, lookback: int = 20,
                 n_states: int = 3, n_paths: int = 2000, q: float = 0.79,
                 seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Returns (q_hi, q_lo) simple returns, shape (n_sessions, n_dec). NaN during warm-up."""
    assert (dec_min % STEP == 0).all(), "decision minutes must be multiples of 5"
    r5 = _five_min_returns(m)
    rv = _pre_open_rv(m)
    k_dec = dec_min // STEP - 1                     # slot index whose close = price at m
    k_max = int(k_dec.max()) + 1
    q_hi = np.full((m.n, len(dec_min)), np.nan)
    q_lo = np.full_like(q_hi, np.nan)

    for i in range(lookback, m.n):
        W = r5[i - lookback:i, :k_max]
        s = np.sqrt((W ** 2).mean(axis=0))
        s = np.where(s > 0, s, np.nanmedian(s[s > 0]) if (s > 0).any() else 1e-6)
        z = W / s
        if n_states > 1:
            cuts = np.quantile(np.abs(z), np.linspace(0, 1, n_states + 1)[1:-1])
            st = np.searchsorted(cuts, np.abs(z))
            cnt = np.ones((n_states, n_states))
            np.add.at(cnt, (st[:, :-1].ravel(), st[:, 1:].ravel()), 1)
            P = cnt / cnt.sum(axis=1, keepdims=True)
            hist = rv[i - lookback:i]
            if np.isfinite(rv[i]) and np.isfinite(hist).all():
                frac = (hist < rv[i]).mean()
                s0 = min(int(frac * n_states), n_states - 1)
            else:
                s0 = n_states // 2
        else:
            st = np.zeros_like(z, dtype=int)
            P = np.ones((1, 1))
            s0 = 0
        order = np.argsort(st.ravel(), kind="stable")
        pool = z.ravel()[order]
        size = np.bincount(st.ravel(), minlength=n_states)
        off = np.concatenate([[0], np.cumsum(size)[:-1]])
        cumP = np.cumsum(P, axis=1)

        rng = np.random.default_rng([seed, i])
        state = np.full(n_paths, s0)
        cum = np.zeros(n_paths)
        out = np.empty((n_paths, len(k_dec)))
        j = 0
        for k in range(k_max):
            if n_states > 1:
                u = rng.random(n_paths)
                state = (u[:, None] > cumP[state]).sum(axis=1)
                state = np.minimum(state, n_states - 1)
            pick = off[state] + (rng.random(n_paths) * np.maximum(size[state], 1)).astype(int)
            cum += s[k] * pool[pick]
            while j < len(k_dec) and k_dec[j] == k:
                out[:, j] = cum
                j += 1
        q_hi[i] = np.expm1(np.quantile(out, q, axis=0))
        q_lo[i] = np.expm1(np.quantile(out, 1 - q, axis=0))
    return q_hi, q_lo


def compute_mc_signals(m: SessionMatrix, interval: int = 30, lookback: int = 20,
                       n_states: int = 3, n_paths: int = 2000, q: float = 0.79,
                       seed: int = 7, base: Signals | None = None) -> Signals:
    """Same Signals object as compute_signals (px, VWAP, daily vol, prev close),
    with the bands replaced by Monte-Carlo quantile bands."""
    s = base if base is not None else compute_signals(m, interval=interval)
    q_hi, q_lo = mc_quantiles(m, s.dec_min, lookback, n_states, n_paths, q, seed)
    hi_ref = np.fmax(s.sess_open, s.prev_close)[:, None]
    lo_ref = np.fmin(s.sess_open, s.prev_close)[:, None]
    ub = hi_ref * (1.0 + np.maximum(q_hi, 0.0))
    lb = lo_ref * (1.0 + np.minimum(q_lo, 0.0))
    sigma = (q_hi - q_lo) / 2.0            # used by the cost filter / readiness check
    return Signals(s.dec_min, s.px, ub, lb, s.vwap, sigma, s.sess_open, s.prev_close, s.daily_vol)
