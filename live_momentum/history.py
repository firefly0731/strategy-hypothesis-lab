"""Pre-open preparation: history -> backtest replay -> today's sizing multipliers.

At each session open the live system recomputes, from HISTORY_START, exactly what the
research pipeline computes: per-symbol unit trades (maker_chase, adopted rules, funding),
RV24, the unscaled portfolio, the vol-target scale and the drawdown throttle. Only bars
closed before the open and funding settled before the open are used.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_intraday_momentum.sessions import build_sessions
from crypto_intraday_momentum.signals import compute_signals
from crypto_intraday_momentum.sizing import pre_open_rv, unit_trades

from .bars import pad_until
from .signal_engine import DataGap, Session
from .sizing_live import SessionSizing, session_sizing
from .strategy import SESSION, SizingParams, backtest_config


@dataclass
class Prepared:
    session: Session
    sizing: SessionSizing
    history: dict              # sym -> regular 1m frame (bars < open), used for live snapshots
    last_bar: dict             # sym -> open_time of the last history bar
    unit_trades: dict          # sym -> research unit trades (for reports)


def prepare(sess: Session, bars: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame],
            ticks: dict[str, float] | None = None, params: SizingParams = SizingParams()) -> Prepared:
    """bars: sym -> regular 1m frame from HISTORY_START (archive + live), funding: sym -> (time, rate)."""
    data, hist, last, uts = {}, {}, {}, {}
    for sym, df in bars.items():
        known = df[df.index < sess.start]
        if not len(known) or known.index[-1] != sess.start - pd.Timedelta(minutes=1):
            # RV24, sigma and the outage filter need every bar up to the open: never size on a gap
            raise DataGap(f"{sym}: history ends at {known.index[-1] if len(known) else None}, "
                          f"need the bar before the open {sess.start - pd.Timedelta(minutes=1)}")
        miss = known.loc[sess.start - pd.Timedelta(hours=24):, "filled"].mean() if "filled" in known else 0.0
        if miss > 0.02:
            raise DataGap(f"{sym}: {miss:.1%} of the 24h before the open are missing bars")
        last[sym] = known.index[-1]
        f = funding.get(sym)
        f = f[f["time"] < sess.start] if f is not None and len(f) else None
        m = build_sessions(pad_until(known, sess.end), SESSION)
        if sess.start not in set(m.start_utc):
            raise ValueError(f"{sym}: session {sess.date.date()} not buildable from history")
        cfg = backtest_config(sym, tick=None if ticks is None else ticks.get(sym), include_funding=f is not None)
        t = unit_trades(m, compute_signals(m), cfg, f)
        data[sym] = (m, t, pre_open_rv(known, m))
        hist[sym] = known
        uts[sym] = t
    sz = session_sizing(data, sess.date, params)
    return Prepared(sess, sz, hist, last, uts)
