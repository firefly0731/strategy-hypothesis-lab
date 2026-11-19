"""Cut a continuous 24/7 minute series into fixed "sessions".

Session i is the bar range [start_utc[i], start_utc[i] + n_minutes).
Bar k of a session is the 1m kline whose open_time == start_utc + k min, so
it covers [start + k, start + k + 1). Its close is known at minute k + 1.

US mode converts 09:30 America/New_York to UTC *per date* via zoneinfo, so
the DST shift (13:30 UTC in summer, 14:30 UTC in winter) is handled.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SessionSpec:
    name: str
    tz: str
    start: str            # local "HH:MM"
    n_minutes: int
    calendar: str         # "xnys" (NYSE trading days) | "all" (every day)
    skip_early_closes: bool = True


US = SessionSpec("us", "America/New_York", "09:30", 390, "xnys")
UTC = SessionSpec("utc", "UTC", "00:00", 1440, "all")
SPECS = {"us": US, "utc": UTC}


@dataclass
class SessionMatrix:
    spec: SessionSpec
    dates: pd.DatetimeIndex      # local session date
    start_utc: pd.DatetimeIndex  # open_time of bar 0
    O: np.ndarray                # (n_sessions, n_minutes)
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray                # base volume
    QV: np.ndarray               # quote volume (for exact VWAP)
    filled: np.ndarray           # bool, synthetic bars from outages
    tradable: np.ndarray         # (n_sessions,) False if the previous session had many outage bars
    pre_C: np.ndarray | None = None  # (n_sessions, n_pre) closes of the bars just BEFORE the open
    TBV: np.ndarray | None = None    # taker (aggressive) buy volume per bar, base units

    @property
    def n(self) -> int:
        return len(self.dates)

    def bar_time(self, i: int, k: int) -> pd.Timestamp:
        """open_time (UTC) of bar k in session i."""
        return self.start_utc[i] + pd.Timedelta(minutes=int(k))


def session_dates(spec: SessionSpec, start: str, end: str) -> pd.DatetimeIndex:
    if spec.calendar == "all":
        return pd.date_range(start, end, freq="D")
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS")
    lo = max(pd.Timestamp(start), cal.first_session)
    hi = min(pd.Timestamp(end), cal.last_session)
    days = cal.sessions_in_range(lo, hi)
    if spec.skip_early_closes:
        days = days.difference(cal.early_closes)
    return pd.DatetimeIndex(days).tz_localize(None)


def build_sessions(df: pd.DataFrame, spec: SessionSpec, max_filled_frac: float = 0.02,
                   n_pre: int = 60) -> SessionMatrix:
    """df: output of data.load_klines (regular 1-minute UTC grid)."""
    idx = df.index
    t0 = idx[0]
    dates = session_dates(spec, str(idx[0].date()), str(idx[-1].date()))
    hh, mm = map(int, spec.start.split(":"))
    local = pd.DatetimeIndex(dates) + pd.Timedelta(hours=hh, minutes=mm)
    start_utc = local.tz_localize(spec.tz, nonexistent="raise", ambiguous="raise").tz_convert("UTC")

    pos0 = ((start_utc - t0) // pd.Timedelta(minutes=1)).to_numpy().astype(np.int64)
    ok = (pos0 - n_pre >= 0) & (pos0 + spec.n_minutes <= len(idx))
    pos = pos0[ok][:, None] + np.arange(spec.n_minutes)[None, :]

    def take(col):
        return df[col].to_numpy()[pos]

    sel = np.flatnonzero(ok)
    filled = take("filled").astype(bool)
    m = SessionMatrix(
        spec=spec,
        dates=pd.DatetimeIndex(dates[sel]),
        start_utc=pd.DatetimeIndex(start_utc[sel]),
        O=take("open"), H=take("high"), L=take("low"), C=take("close"),
        V=take("volume"), QV=take("quote_volume"),
        filled=filled,
        # causal: decided from the *previous* session's data quality only.
        # (Using this session's own outage share would peek at future bars.)
        tradable=np.concatenate([[True], filled[:-1].mean(axis=1) <= max_filled_frac]),
        # pre-open bars [start - n_pre, start): all closed by the session open
        TBV=take("taker_buy_volume") if "taker_buy_volume" in df else None,
        pre_C=df["close"].to_numpy()[pos[:, :1] - n_pre + np.arange(n_pre)[None, :]] if n_pre else None,
    )
    # sanity: bar k of session i really is the kline opening at start + k
    assert (df.index[pos[:, 0]] == m.start_utc).all()
    return m
