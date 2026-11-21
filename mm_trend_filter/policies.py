"""Quote permissions per bar (DESIGN.md "Policies"). Window j covers bars dm[j] .. dm[j]+29 and
its state uses bars < dm[j] only (compute_signals / prior-session means)."""
from __future__ import annotations

import numpy as np

from crypto_intraday_momentum.signals import _rolling_prior_mean


def window_state(sig) -> np.ndarray:
    """(n_sess, n_dec): +1 px > UB, -1 px < LB, 0 otherwise (NaN bands -> 0)."""
    up = np.nan_to_num(sig.px > sig.ub, nan=False) & np.isfinite(sig.ub)
    dn = np.nan_to_num(sig.px < sig.lb, nan=False) & np.isfinite(sig.lb)
    return up.astype(int) - dn.astype(int)


def to_bars(win: np.ndarray, dm: np.ndarray, n_k: int, fill=0) -> np.ndarray:
    """Spread a per-window array onto bars; bars before dm[0] get `fill`."""
    out = np.full((win.shape[0], n_k), fill, dtype=win.dtype)
    edges = list(dm) + [n_k]
    for j in range(len(dm)):
        out[:, edges[j]:edges[j + 1]] = win[:, j:j + 1]
    return out


def path_length_state(C: np.ndarray, O0: np.ndarray, dm: np.ndarray, lookback=14, mult=1.5) -> np.ndarray:
    """vol_off control: 1 when Σ|Δlog C| over the 30 bars before dm exceeds mult × its mean at
    the same minute over the previous `lookback` sessions."""
    prev = np.concatenate([O0[:, None], C[:, :-1]], axis=1)
    a = np.abs(np.log(C / prev))
    cs = np.concatenate([np.zeros((C.shape[0], 1)), np.cumsum(a, axis=1)], axis=1)
    rv = cs[:, dm] - cs[:, dm - 30]
    base = _rolling_prior_mean(rv, lookback)
    return (np.nan_to_num(rv > mult * base, nan=False) & np.isfinite(base)).astype(int)


def permissions(name: str, state: np.ndarray, dm: np.ndarray, n_k: int, vol_state=None, rng=None, p=None):
    """-> (allow_bid, allow_ask, flat) bool arrays (n_sess, n_k)."""
    n = state.shape[0]
    t = np.ones((n, n_k), dtype=np.bool_)
    flat = np.zeros((n, n_k), dtype=np.bool_)
    bs = to_bars(state, dm, n_k)
    if name == "none":
        return t, t.copy(), flat
    if name == "band_off":
        ok = bs == 0
        return ok, ok.copy(), flat
    if name == "band_flat":
        ok = bs == 0
        flat[:, dm] = state != 0
        return ok, ok.copy(), flat
    if name == "band_skew":
        return bs != -1, bs != 1, flat
    if name == "sticky_off":
        ok = np.maximum.accumulate(np.abs(bs), axis=1) == 0
        return ok, ok.copy(), flat
    if name == "vol_off":
        ok = to_bars(vol_state, dm, n_k) == 0
        return ok, ok.copy(), flat
    if name == "random_off":
        off = (rng.random(state.shape) < p).astype(int)
        ok = to_bars(off, dm, n_k) == 0
        return ok, ok.copy(), flat
    raise ValueError(name)


POLICIES = ["none", "band_off", "band_flat", "band_skew", "sticky_off", "vol_off"]
