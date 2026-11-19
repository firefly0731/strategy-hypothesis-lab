"""Order-flow features from Binance taker buy volume, look-ahead safe.

For a bar, taker buy volume (TBV) is the volume executed by aggressive buyers. The
rest (V - TBV) is aggressive selling. Net aggressor imbalance over a set of bars:

    imb = (2 * sum TBV - sum V) / sum V        in [-1, 1]

At decision minute m only bars 0..m-1 are used, as in signals.py.
"""
from __future__ import annotations

import numpy as np

from .sessions import SessionMatrix
from .signals import _rolling_prior_mean


def _imb(tbv_cum, v_cum, a, b):
    """Imbalance over bars [a, b) using cumulative sums padded with a leading 0."""
    v = v_cum[:, b] - v_cum[:, a]
    d = 2 * (tbv_cum[:, b] - tbv_cum[:, a]) - v
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(v > 0, d / v, 0.0)


def flow_features(m: SessionMatrix, dec_min: np.ndarray, interval: int = 30,
                  lookback: int = 14) -> dict[str, np.ndarray]:
    if m.TBV is None:
        raise ValueError("session matrix has no taker buy volume; reload data")
    pad = np.zeros((m.n, 1))
    tc = np.concatenate([pad, np.cumsum(m.TBV, axis=1)], axis=1)
    vc = np.concatenate([pad, np.cumsum(m.V, axis=1)], axis=1)
    imb_open = np.stack([_imb(tc, vc, 0, k) for k in dec_min], axis=1)                  # since open
    imb_last = np.stack([_imb(tc, vc, max(k - interval, 0), k) for k in dec_min], axis=1)  # last interval
    # standardise against the same minute in previous sessions (removes a persistent bias)
    mu = _rolling_prior_mean(imb_open, lookback)
    sd = np.sqrt(np.maximum(_rolling_prior_mean(imb_open ** 2, lookback) - mu ** 2, 1e-12))
    return {"imb_open": imb_open, "imb_last": imb_last, "imb_open_z": (imb_open - mu) / sd}
