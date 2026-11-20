"""Look-ahead perturbation tests for the live code path (same method as
crypto_intraday_momentum/tests/test_lookahead.py): every bar from time T onward is
replaced with random data; everything decided before T must stay bit-for-bit identical."""
import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.sessions import US, build_sessions
from live_momentum.replay import replay_session
from live_momentum.signal_engine import DataGap, decision_times, session_for, snapshot
from live_momentum.strategy import backtest_config

from .conftest import perturb_from

SNAP_FIELDS = ("px", "ub", "lb", "vwap", "sigma")


def _same_snap(a, b):
    assert a.ready == b.ready and a.sess_open == b.sess_open and a.prev_close == b.prev_close
    for f in SNAP_FIELDS:
        assert np.array_equal(getattr(a, f), getattr(b, f), equal_nan=True), f


def test_snapshot_ignores_bars_at_or_after_now(synth_df):
    """Passing the full history (incl. the future) gives the same snapshot as passing only
    the closed bars: snapshot() cuts its input at `now` itself."""
    m = build_sessions(synth_df, US)
    for day in m.dates[[20, 35, 50]]:
        for now in decision_times(session_for(day))[::3]:
            full = snapshot(synth_df, now)
            cut = snapshot(synth_df[synth_df.index < now], now)
            _same_snap(full, cut)
            assert np.isnan(full.px[full.dec_min > full.t]).all()


@pytest.mark.parametrize("k_dec", [0, 3, 7])
def test_snapshot_perturbation(synth_df, k_dec):
    m = build_sessions(synth_df, US)
    day = m.dates[40]
    times = decision_times(session_for(day))
    T = times[k_dec]
    pert = perturb_from(synth_df, T)
    for now in times[: k_dec + 1]:                 # all decisions at or before T
        _same_snap(snapshot(synth_df, now), snapshot(pert, now))
    later = snapshot(synth_df, times[k_dec + 1]), snapshot(pert, times[k_dec + 1])
    assert later[0].px[k_dec + 1] != later[1].px[k_dec + 1]     # perturbation did bite


def test_replay_ignores_future_bars(synth_df):
    cfg = backtest_config("BTCUSDT", include_funding=False)
    m = build_sessions(synth_df, US)
    days = m.dates[16:]
    base = {d: replay_session(synth_df, d, cfg)[0] for d in days}
    trades = pd.concat([t for t in base.values() if len(t)])
    assert len(trades) > 20
    T = trades["exit_time"].iloc[len(trades) // 2] + pd.Timedelta(minutes=1)
    pert = perturb_from(synth_df, T)
    n_cmp = 0
    for d in days:
        sess = session_for(d)
        if sess.start >= T:
            break
        a = base[d]
        b = replay_session(pert, d, cfg)[0]
        cols = ["side", "entry_time", "exit_time", "entry_px", "exit_px", "entry_maker", "exit_maker", "exit_reason"]
        keep = a[a["exit_time"] < T - pd.Timedelta(minutes=1)] if len(a) else a
        if len(keep):
            pd.testing.assert_frame_equal(keep[cols].reset_index(drop=True),
                                          b[cols].iloc[: len(keep)].reset_index(drop=True))
            n_cmp += len(keep)
    assert n_cmp > 10


def test_snapshot_refuses_stale_data(synth_df):
    m = build_sessions(synth_df, US)
    now = decision_times(session_for(m.dates[30]))[2]
    stale = synth_df[synth_df.index < now - pd.Timedelta(minutes=3)]
    with pytest.raises(DataGap):
        snapshot(stale, now)


def test_dst_and_holidays():
    assert session_for("2024-03-08").start == pd.Timestamp("2024-03-08 14:30", tz="UTC")
    assert session_for("2024-03-11").start == pd.Timestamp("2024-03-11 13:30", tz="UTC")
    assert session_for("2026-11-26") is None          # Thanksgiving
    assert session_for("2026-11-27") is None          # early close -> not traded
    assert session_for("2026-11-21") is None          # Saturday
    assert session_for("2026-11-20").start == pd.Timestamp("2026-11-20 14:30", tz="UTC")
