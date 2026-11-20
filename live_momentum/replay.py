"""Replay historical sessions through the live code path, minute by minute.

For every minute boundary of a session the executor is stepped; at decision minutes the
signal snapshot is computed from the bars closed at that moment only (signal_engine.snapshot
cuts the input at `now`). Fills come from SimBarVenue, which holds the session's bars as the
"market". The output has the same columns as run_backtest's trades for comparison.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_intraday_momentum.backtest import Config

from .executor import MakerChaseExecutor, SimBarVenue
from .signal_engine import Rules, Snapshot, session_for, snapshot, target_position


def rules_from(cfg: Config) -> Rules:
    return Rules(cfg.entry_cutoff_min, cfg.vwap_confirm_k, cfg.cost_filter_mult * cfg.round_trip_cost())


def replay_session(df: pd.DataFrame, day, cfg: Config, qty: float = 1.0, history_days: int = 45):
    """Returns (trades DataFrame, list of decision snapshots)."""
    sess = session_for(day)
    if sess is None:
        raise ValueError(f"{day} is not a trading session")
    bars = df.loc[sess.start: sess.end - pd.Timedelta(minutes=1)]
    if len(bars) != sess.n_min:
        raise ValueError(f"incomplete session {day}")
    O, H, L, C = (bars[c].to_numpy() for c in ("open", "high", "low", "close"))
    venue = SimBarVenue(O, H, L, C, cfg.taker_slippage_bps)
    rules = rules_from(cfg)
    # the history window only needs to reach back HISTORY_DAYS; slicing here is a speed-up
    hist = df.loc[sess.start - pd.Timedelta(days=history_days): sess.end]

    first: Snapshot | None = None
    snaps: list[Snapshot] = []
    ex: MakerChaseExecutor | None = None
    for t in range(1, sess.n_min + 1):
        now = sess.start + pd.Timedelta(minutes=t)
        if first is None:
            first = snapshot(hist, now, history_days=history_days)
            ex = MakerChaseExecutor(venue, cfg, first.dec_min, sess.n_min, qty_fn=lambda t_, last: qty,
                                    cid_prefix=f"lm{sess.date:%m%d}")
        want_fn = None
        if first.ready and np.any(first.dec_min == t):
            snap = snapshot(hist, now, history_days=history_days)
            snaps.append(snap)
            j = snap.j()
            want_fn = (lambda pos, s=snap, j=j:
                       target_position(pos, s.px[j], s.ub[j], s.lb[j], s.vwap[j], s.sigma[j], s.t, rules))
        ex.step(t, C[t - 1], want_fn)

    rows = []
    n = sess.n_min
    for r in ex.trades:
        rows.append(dict(date=sess.date, side=r.side,
                         entry_time=sess.start + pd.Timedelta(minutes=r.entry_bar),
                         exit_time=sess.start + pd.Timedelta(minutes=min(r.exit_bar, n - 1)),
                         entry_px=r.entry_px, exit_px=r.exit_px, entry_maker=r.entry_maker,
                         exit_maker=r.exit_maker, exit_reason=r.exit_reason, dec_j=r.dec_j,
                         dec_min=int(first.dec_min[r.dec_j]), entry_kind=r.entry_kind,
                         hold_min=r.exit_bar - r.entry_bar))
    return pd.DataFrame(rows), snaps, first
