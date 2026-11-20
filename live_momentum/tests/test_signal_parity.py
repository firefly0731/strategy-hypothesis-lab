"""Phase 0: the live code path must reproduce run_backtest decision by decision.

For every session the live replay steps the executor minute by minute and computes each
decision's signals from the bars closed at that moment only. We require:
  * signals (px, UB, LB, VWAP, sigma) equal to the full-history backtest (float rounding only)
  * the per-session `ready` flag identical
  * trades identical: side, entry/exit time, entry/exit price, maker flags, exit reason,
    decision index and entry kind
"""
import os

import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.backtest import run_backtest
from crypto_intraday_momentum.sessions import US, build_sessions
from crypto_intraday_momentum.signals import compute_signals
from live_momentum.replay import replay_session
from live_momentum.strategy import SYMBOLS, backtest_config

from .conftest import real_data

COLS = ["side", "entry_time", "exit_time", "entry_px", "exit_px", "entry_maker", "exit_maker",
        "exit_reason", "dec_j", "entry_kind"]
RTOL = 1e-12


def compare(df, cfg, days):
    m = build_sessions(df, US)
    s = compute_signals(m)
    bt = run_backtest(m, s, cfg).trades
    stats = dict(sessions=0, decisions=0, trades=0, maker_entries=0, maker_exits=0, reasons=set(), flips=0)
    live_all = []
    for day in days:
        i = int(np.flatnonzero(m.dates == day)[0])
        live, snaps, first = replay_session(df, day, cfg)
        ready = m.tradable[i] and np.isfinite(s.sigma[i]).all() and np.isfinite(s.prev_close[i])
        assert first.ready == ready, day
        assert np.array_equal([first.sess_open, first.prev_close], [s.sess_open[i], s.prev_close[i]],
                              equal_nan=True), day
        np.testing.assert_allclose(first.sigma, s.sigma[i], rtol=RTOL)
        for sn in snaps:
            j = sn.j()
            for name in ("px", "ub", "lb", "vwap"):
                np.testing.assert_allclose(getattr(sn, name)[j], getattr(s, name)[i, j], rtol=RTOL,
                                           err_msg=f"{day.date()} {name} j={j}")
        b = bt[bt["date"] == day].reset_index(drop=True) if len(bt) else bt
        if len(b) == 0:
            assert len(live) == 0, f"{day.date()}: live traded, backtest did not\n{live}"
        else:
            pd.testing.assert_frame_equal(live[COLS].reset_index(drop=True), b[COLS], check_dtype=False,
                                          obj=f"trades {day.date()}")
        stats["sessions"] += 1
        stats["decisions"] += len(snaps)
        stats["trades"] += len(live)
        if len(live):
            stats["maker_entries"] += int(live["entry_maker"].sum())
            stats["maker_exits"] += int(live["exit_maker"].sum())
            stats["reasons"] |= set(live["exit_reason"])
            stats["flips"] += int((live["entry_kind"] == "flip").sum())
            live_all.append(live)
    return stats, (pd.concat(live_all) if live_all else pd.DataFrame())


VARIANTS = {
    "adopted": {},
    "no_filters": dict(entry_cutoff_min=None, vwap_confirm_k=0.0),
    # far limits: many maker orders time out -> market fallback paths
    "wide_offset": dict(entry_cutoff_min=None, vwap_confirm_k=0.0, maker_offset_bps=8.0),
    "short_timeout": dict(entry_cutoff_min=None, vwap_confirm_k=0.0, maker_offset_bps=4.0, maker_timeout=2),
    # cost filter on: blocks new legs when sigma < mult x round-trip cost
    "cost_filter": dict(cost_filter_mult=9.0),
}


def test_backtest_config_matches_unit_trades():
    """The parity reference must be the backtest the adopted pipeline runs (unit_trades)."""
    cfg = backtest_config("BTCUSDT")
    assert cfg.sizing == "fixed" and cfg.fixed_leverage == 1.0
    assert cfg.entry_cutoff_min == 270 and cfg.vwap_confirm_k == 0.6
    assert (cfg.entry_mode, cfg.entry_fallback, cfg.exit_mode) == ("maker", "taker", "maker")


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_parity_synthetic(synth_df, variant):
    cfg = backtest_config("BTCUSDT", include_funding=False, **VARIANTS[variant])
    m = build_sessions(synth_df, US)
    st, _ = compare(synth_df, cfg, m.dates)          # every session, incl. the warm-up ones
    if variant == "cost_filter":
        base, _ = compare(synth_df, backtest_config("BTCUSDT", include_funding=False), m.dates)
        assert 0 < st["trades"] < base["trades"]        # the filter actually blocked entries
        return
    # the comparison must actually exercise the state machine
    assert st["trades"] > 30 and st["maker_entries"] > 0 and st["maker_exits"] > 0
    assert {"stop", "eod"} <= st["reasons"]
    if variant in ("wide_offset", "short_timeout"):           # market fallbacks happened
        assert st["maker_entries"] < st["trades"] and st["maker_exits"] < st["trades"]


@pytest.mark.parametrize("variant", ["adopted", "no_filters", "wide_offset", "short_timeout"])
def test_parity_synthetic_flips(synth_flip_df, variant):
    """Sessions with a sharp reversal: exit then entry in the opposite direction, with the
    follow-up entry sent after a maker exit (next minute) or a market exit (same minute)."""
    cfg = backtest_config("BTCUSDT", include_funding=False, **VARIANTS[variant])
    m = build_sessions(synth_flip_df, US)
    st, live = compare(synth_flip_df, cfg, m.dates)
    assert st["flips"] >= 3 and "flip" in st["reasons"]
    fl = live[live["exit_reason"] == "flip"]
    assert fl["exit_maker"].any()
    if variant in ("wide_offset", "short_timeout"):
        assert (~fl["exit_maker"]).any()


def test_parity_with_outages(synth_outage_df):
    """Missing minutes (filled bars) and a session with > 2% outage bars: the next session
    must be skipped by both the backtest and the live path."""
    df, bad_day = synth_outage_df
    m = build_sessions(df, US)
    assert m.filled.sum() > 60                       # outage bars inside sessions
    i_bad = int(np.flatnonzero(m.dates == bad_day)[0])
    assert m.filled[i_bad].mean() > 0.02 and not m.tradable[i_bad + 1]
    st, _ = compare(df, backtest_config("BTCUSDT", include_funding=False), m.dates)
    assert st["trades"] > 20


N_REAL = int(os.environ.get("LIVE_PARITY_SESSIONS", "60"))


@real_data
@pytest.mark.parametrize("sym", SYMBOLS)
def test_parity_real_recent_sessions(real_dfs, sym):
    """Last N_REAL sessions (default 60; LIVE_PARITY_SESSIONS=250 for a longer check)."""
    df = real_dfs[sym]
    cfg = backtest_config(sym, include_funding=False)
    m = build_sessions(df, US)
    days = m.dates[-N_REAL:]
    st, live = compare(df, cfg, days)
    print(f"\n{sym}: {st['sessions']} sessions, {st['decisions']} decisions, {st['trades']} trades, "
          f"maker entries {st['maker_entries']}, maker exits {st['maker_exits']}, reasons {sorted(st['reasons'])}")
    assert st["sessions"] == N_REAL and st["decisions"] > 0
