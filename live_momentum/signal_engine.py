"""Decision-time signals for the live system.

The signals are computed by the research code itself (`build_sessions` + `compute_signals`)
on the bars that are CLOSED at the decision time; the unknown rest of the session is padded
with NaN. Nothing at or after `now` can enter, by construction: the input is cut at `now`
before anything else happens.

The only differences from the full-history backtest are floating-point rounding in the
rolling means (different cumsum origin, ~1e-16 relative). Decisions and trades must match
exactly; `tests/test_signal_parity.py` checks both.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_intraday_momentum.sessions import SessionSpec, build_sessions, session_dates
from crypto_intraday_momentum.signals import compute_signals, decision_minutes

from .bars import ONE_MIN, closed_before, pad_until
from .strategy import RULES, SESSION

HISTORY_DAYS = 45            # >= 14 prior NYSE sessions + 1 for the outage filter, with holidays


class DataGap(RuntimeError):
    """Bars missing right before the decision time: do not decide on stale data."""


@dataclass(frozen=True)
class Session:
    date: pd.Timestamp       # NY session date (naive)
    start: pd.Timestamp      # UTC open_time of bar 0
    n_min: int

    @property
    def end(self) -> pd.Timestamp:
        return self.start + pd.Timedelta(minutes=self.n_min)

    def minute(self, now: pd.Timestamp) -> int:
        return int((now - self.start) // ONE_MIN)


def session_for(day, spec: SessionSpec = SESSION) -> Session | None:
    """The trading session on NY date `day`, or None (weekend, holiday, early close)."""
    day = pd.Timestamp(day).normalize()
    if len(session_dates(spec, str(day.date()), str(day.date()))) == 0:
        return None
    hh, mm = map(int, spec.start.split(":"))
    local = (day + pd.Timedelta(hours=hh, minutes=mm)).tz_localize(spec.tz)
    return Session(day, local.tz_convert("UTC"), spec.n_minutes)


def session_at(now: pd.Timestamp, spec: SessionSpec = SESSION) -> Session | None:
    """Session that contains `now` (start <= now <= end), if any."""
    s = session_for(now.tz_convert(spec.tz).tz_localize(None), spec)
    return s if s is not None and s.start <= now <= s.end else None


@dataclass(frozen=True)
class Snapshot:
    """Everything the strategy may know about today's session at `now`."""
    session: Session
    now: pd.Timestamp
    t: int                   # minutes since the open (= bars closed in this session)
    ready: bool              # backtest's per-session `ready` flag
    sess_open: float
    prev_close: float
    dec_min: np.ndarray
    px: np.ndarray           # (n_dec,) NaN for decisions after `now`
    ub: np.ndarray
    lb: np.ndarray
    vwap: np.ndarray
    sigma: np.ndarray        # (n_dec,) from prior sessions only
    n_prior: int = 0         # prior sessions in the history window (need >= 14 for sigma)

    def j(self) -> int | None:
        """Index of the decision at `now`, or None if `now` is not a decision time."""
        k = np.flatnonzero(self.dec_min == self.t)
        return int(k[0]) if k.size else None


def snapshot(df: pd.DataFrame, now: pd.Timestamp, spec: SessionSpec = SESSION,
             history_days: int = HISTORY_DAYS, require_last_bar: bool = True) -> Snapshot:
    """df: regular 1m grid (bars.regularize / load_klines). Bars not closed at `now` are dropped."""
    sess = session_at(now, spec)
    if sess is None:
        raise ValueError(f"{now} is not inside a trading session")
    t = sess.minute(now)
    if t < 1:
        raise ValueError("session open bar is not closed yet")
    known = closed_before(df, now)
    known = known[known.index >= sess.start - pd.Timedelta(days=history_days)]
    if require_last_bar and (len(known) == 0 or known.index[-1] != now - ONE_MIN):
        raise DataGap(f"last closed bar at {now} should be {now - ONE_MIN}, "
                      f"have {known.index[-1] if len(known) else None}")
    m = build_sessions(pad_until(known, sess.end), spec)
    hit = np.flatnonzero(m.start_utc == sess.start)
    if not hit.size:
        raise DataGap(f"session {sess.date.date()} not buildable from the bars given")
    i = int(hit[0])
    s = compute_signals(m)
    ready = bool(m.tradable[i] and np.isfinite(s.sigma[i]).all() and np.isfinite(s.prev_close[i]))
    future = s.dec_min > t
    def row(a):
        r = a[i].astype(float).copy()
        r[future] = np.nan
        return r
    return Snapshot(sess, now, t, ready, float(s.sess_open[i]), float(s.prev_close[i]),
                    s.dec_min.copy(), row(s.px), row(s.ub), row(s.lb), row(s.vwap),
                    s.sigma[i].astype(float).copy(), n_prior=i)


@dataclass(frozen=True)
class Rules:
    entry_cutoff_min: int | None = RULES["entry_cutoff_min"]
    vwap_confirm_k: float = RULES["vwap_confirm_k"]
    min_sigma: float = 0.0           # cost filter (off in the adopted configuration)


def target_position(pos: int, p: float, ub: float, lb: float, vw: float, sigma: float,
                    t: int, rules: Rules = Rules()) -> int:
    """Wanted position after the decision at minute t (same rules as run_backtest)."""
    if pos == 0:
        want = 1 if p > ub else (-1 if p < lb else 0)
    elif pos == 1:
        want = 1 if p >= max(ub, vw) else (-1 if p < lb else 0)
    else:
        want = -1 if p <= min(lb, vw) else (1 if p > ub else 0)
    if want != 0 and want != pos:            # filters block the new leg only
        if sigma < rules.min_sigma:
            want = 0
        elif rules.entry_cutoff_min is not None and t >= rules.entry_cutoff_min:
            want = 0
        elif rules.vwap_confirm_k > 0 and want * (p / vw - 1.0) < rules.vwap_confirm_k * sigma:
            want = 0
    return want


def decision_times(sess: Session, interval: int = 30, first: int = 30) -> list[pd.Timestamp]:
    return [sess.start + pd.Timedelta(minutes=int(m)) for m in decision_minutes(sess.n_min, interval, first)]
