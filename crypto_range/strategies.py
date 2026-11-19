"""Pre-registered mean-reversion ideas A–E (see README). Every function maps a
SessionMatrix (+ the continuous kline frame where needed) to `Orders`.

Look-ahead rule: everything used for the decision at minute t of session i comes
from bars 0..t-1 of session i, from earlier sessions, or from the continuous
series up to the bar that opens at start_utc[i] + t - 1 min.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_intraday_momentum.sessions import US, SessionMatrix, SessionSpec
from crypto_intraday_momentum.signals import _rolling_prior_mean

from .engine import Orders

PRE = SessionSpec("pre", "America/New_York", "07:00", 150, "xnys")    # 07:00-09:30 NY
OFF = SessionSpec("off", "America/New_York", "20:00", 720, "all")     # 20:00-08:00 NY
MAC = SessionSpec("mac", "America/New_York", "08:30", 90, "xnys")     # 08:30-10:00 NY
OPN = SessionSpec("opn", "America/New_York", "07:00", 210, "xnys")    # 07:00-10:30 NY
SPECS = {"A": PRE, "B": US, "C": OFF, "D": US, "E": MAC, "F": OPN}


# ----------------------------------------------------------------------------- features

def noise_sigma(m: SessionMatrix, dm: np.ndarray, lookback: int = 14) -> np.ndarray:
    """mean |C[m-1]/O0 - 1| at each decision minute over the prior `lookback` sessions."""
    move = np.abs(m.C[:, dm - 1] / m.O[:, :1] - 1.0)
    return _rolling_prior_mean(move, lookback)


def vwap_at(m: SessionMatrix, dm: np.ndarray) -> np.ndarray:
    cqv = np.cumsum(m.QV, axis=1)[:, dm - 1]
    cv = np.cumsum(m.V, axis=1)[:, dm - 1]
    px = m.C[:, dm - 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cv > 0, cqv / cv, px)


def variance_ratio(m: SessionMatrix, bin_min: int = 30, lookback: int = 20) -> np.ndarray:
    """Trailing VR for session i from sessions i-lookback..i-1:
    sum(session return^2) / sum(sum of bin-return^2). >1 trending, <1 mean-reverting."""
    n_min = m.C.shape[1]
    edges = np.arange(bin_min, n_min + 1, bin_min) - 1
    px = np.concatenate([m.O[:, :1], m.C[:, edges]], axis=1)
    rb = np.diff(np.log(px), axis=1)
    num = rb.sum(axis=1) ** 2
    den = (rb ** 2).sum(axis=1)
    x = np.stack([num, den], axis=1)
    mu = _rolling_prior_mean(x, lookback)
    with np.errstate(invalid="ignore", divide="ignore"):
        return mu[:, 0] / mu[:, 1]


def sample_at(series: pd.Series, m: SessionMatrix, dm: np.ndarray) -> np.ndarray:
    """Value of a causal per-minute series (indexed by bar open_time) at the bar that
    opens at start + t - 1, i.e. the last bar closed at decision minute t."""
    st = m.start_utc.as_unit("ns").asi8
    times = st[:, None] + (dm[None, :] - 1).astype(np.int64) * 60_000_000_000
    idx = series.index.as_unit("ns").asi8
    pos = np.searchsorted(idx, times.ravel())
    ok = (pos < len(idx)) & (idx[np.minimum(pos, len(idx) - 1)] == times.ravel())
    out = np.full(times.size, np.nan)
    out[ok] = series.to_numpy()[pos[ok]]
    return out.reshape(times.shape)


def _orders(dm, side, target=None, stop=None, tstop=None):
    shp = side.shape
    nan = np.full(shp, np.nan)
    return Orders(dm, side.astype(np.int8),
                  nan if target is None else target,
                  nan.copy() if stop is None else stop,
                  np.broadcast_to(tstop, shp).astype(np.int64))


def _fade(dev: np.ndarray, thr: np.ndarray) -> np.ndarray:
    """-1 if dev > thr, +1 if dev < -thr, 0 otherwise (NaN -> 0)."""
    with np.errstate(invalid="ignore"):
        s = np.where(dev > thr, -1, np.where(dev < -thr, 1, 0))
    s[~(np.isfinite(dev) & np.isfinite(thr))] = 0
    return s


# ----------------------------------------------------------------------------- ideas

def idea_A(m: SessionMatrix, k: float = 1.0, target: str = "anchor", **_) -> Orders:
    dm = np.arange(30, 121, 15)
    sig = noise_sigma(m, dm, 14)
    o0 = m.O[:, :1]
    px = m.C[:, dm - 1]
    side = _fade(px / o0 - 1.0, k * sig)
    tgt = np.broadcast_to(o0, side.shape).astype(float) if target == "anchor" else None
    return _orders(dm, side, tgt, tstop=np.full(len(dm), m.C.shape[1]))


def idea_B(m: SessionMatrix, k: float = 1.5, vr_filter: bool = True, hold: int = 60, **_) -> Orders:
    dm = np.arange(30, 361, 5)
    sig = noise_sigma(m, dm, 14)
    vw = vwap_at(m, dm)
    px = m.C[:, dm - 1]
    side = _fade(px / vw - 1.0, k * sig * m.O[:, :1] / vw)
    if vr_filter:
        vr = variance_ratio(m, 30, 20)
        side[~(vr < 1.0)] = 0
    tstop = np.minimum(dm + hold, m.C.shape[1])
    return _orders(dm, side, vw.copy(), tstop=tstop)


def rolling_band(df: pd.DataFrame, win: int = 120) -> tuple[pd.Series, pd.Series]:
    c = df["close"]
    return c.rolling(win, min_periods=win).mean(), c.rolling(win, min_periods=win).std()


def idea_C(m: SessionMatrix, df: pd.DataFrame, k: float = 2.0, vr_filter: bool = False,
           hold: int = 60, band=None, **_) -> Orders:
    dm = np.arange(60, m.C.shape[1] - 14, 15)
    mu, sd = band if band is not None else rolling_band(df, 120)
    mu_s, sd_s = sample_at(mu, m, dm), sample_at(sd, m, dm)
    px = m.C[:, dm - 1]
    side = _fade(px - mu_s, k * sd_s)
    if vr_filter:
        vr = variance_ratio(m, 30, 20)
        side[~(vr < 1.0)] = 0
    tstop = np.minimum(dm + hold, m.C.shape[1])
    return _orders(dm, side, mu_s, tstop=tstop)


def idea_D(m: SessionMatrix, x: float = 1.0, h: int = 30, **_) -> Orders:
    dm = np.arange(30, 361, 30)
    px = m.C[:, dm - 1]
    prev = np.concatenate([m.O[:, :1], m.C[:, dm[:-1] - 1]], axis=1)
    r30 = px / prev - 1.0
    edges = np.arange(30, m.C.shape[1] + 1, 30) - 1
    lv = np.log(np.concatenate([m.O[:, :1], m.C[:, edges]], axis=1))
    ms = (np.diff(lv, axis=1) ** 2).mean(axis=1)            # known at session end
    s30 = np.sqrt(_rolling_prior_mean(ms[:, None], 20))     # prior sessions only
    side = _fade(r30, x * s30)
    tstop = np.minimum(dm + h, m.C.shape[1])
    return _orders(dm, side, tstop=tstop)


def idea_E(m: SessionMatrix, x: float = 2.0, h: int = 60, **_) -> Orders:
    dm = np.array([15])
    o0 = m.O[:, :1]
    r = m.C[:, dm - 1] / o0 - 1.0
    sig = _rolling_prior_mean(np.abs(r), 20)
    side = _fade(r, x * sig)
    tgt = np.broadcast_to(o0, side.shape).astype(float)
    return _orders(dm, side, tgt, tstop=np.array([h]))


def idea_F(m: SessionMatrix, anchor: str = "08:30", k: float = 1.0, exit: str = "10:00", **_) -> Orders:
    """POST-HOC (added after A-E, see README): fade the pre-open move at the US open.
    Session 07:00-10:30 NY. Decision at 09:30 (minute 150, sees bars up to 09:29):
    r = C[09:29] / O[anchor] - 1, sigma = mean |r| over the prior 20 sessions.
    |r| > k*sigma -> fade with a pure time exit at `exit`."""
    a = {"07:00": 0, "08:00": 60, "08:30": 90}[anchor]
    dm = np.array([150])
    r = m.C[:, dm - 1] / m.O[:, a:a + 1] - 1.0
    sig = _rolling_prior_mean(np.abs(r), 20)
    side = _fade(r, k * sig)
    return _orders(dm, side, tstop=np.array([{"10:00": 180, "10:30": 210}[exit]]))


IDEAS = {"A": idea_A, "B": idea_B, "C": idea_C, "D": idea_D, "E": idea_E, "F": idea_F}

PRIMARY = {
    "A": dict(k=1.0, target="anchor"),
    "B": dict(k=1.5, vr_filter=True),
    "C": dict(k=2.0, vr_filter=False),
    "D": dict(x=1.0, h=30),
    "E": dict(x=2.0, h=60),
    "F": dict(anchor="08:30", k=1.0, exit="10:00"),
}

GRID = {
    "A": [dict(k=k, target=t) for k in (0.75, 1.0, 1.5, 2.0) for t in ("anchor", "none")],
    "B": [dict(k=k, vr_filter=f) for k in (1.0, 1.5, 2.0) for f in (False, True)],
    "C": [dict(k=k, vr_filter=f) for k in (1.5, 2.0, 2.5) for f in (False, True)],
    "D": [dict(x=x, h=h) for x in (0.5, 1.0, 1.5, 2.0) for h in (30, 60)],
    "E": [dict(x=x, h=h) for x in (1.5, 2.0, 3.0) for h in (60, 90)],
    "F": [dict(anchor=a, k=k, exit=e) for a in ("07:00", "08:30") for k in (0.5, 1.0, 2.0)
          for e in ("10:00", "10:30")],
}


def label(params: dict) -> str:
    return "_".join(f"{k}{v}" for k, v in params.items())
