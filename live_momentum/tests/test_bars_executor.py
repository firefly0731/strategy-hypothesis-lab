"""Bar store equivalence with the research loader, and executor unit scenarios."""
import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.data import load_klines
from live_momentum.bars import closed_before, pad_until, regularize
from live_momentum.executor import MakerChaseExecutor, SimBarVenue
from live_momentum.strategy import backtest_config


def test_regularize_matches_research_loader(tmp_path, synth_df):
    raw = synth_df.loc["2024-02-01":"2024-02-29 23:59"].drop(columns="filled")
    rng = np.random.default_rng(0)
    drop = rng.choice(len(raw) - 2, 500, replace=False) + 1           # exchange outages
    raw = raw.drop(raw.index[drop])
    d = tmp_path / "klines_v2" / "TESTUSDT"
    d.mkdir(parents=True)
    raw.reset_index().to_parquet(d / "TESTUSDT-1m-2024-02.parquet", index=False)
    a = load_klines("TESTUSDT", "2024-02", "2024-02", cache=tmp_path)
    b = regularize(raw)
    pd.testing.assert_frame_equal(a[b.columns], b, check_freq=False)
    assert b["filled"].sum() == 500


def test_closed_before_and_pad(synth_df):
    now = pd.Timestamp("2024-02-05 15:00", tz="UTC")
    k = closed_before(synth_df, now)
    assert k.index[-1] == now - pd.Timedelta(minutes=1)
    p = pad_until(k, now + pd.Timedelta(minutes=10))
    assert len(p) == len(k) + 10 and p["close"].iloc[-10:].isna().all() and not p["filled"].iloc[-10:].any()


def _flat(n=390, px=100.0):
    O = np.full(n, px); H = np.full(n, px + 0.05); L = np.full(n, px - 0.05); C = np.full(n, px)
    return O, H, L, C


def _ex(venue, **over):
    cfg = backtest_config("BTCUSDT", tick=0.1, **over)
    return MakerChaseExecutor(venue, cfg, np.arange(30, 390, 30), 390, qty_fn=lambda t, last: 2.0)


def test_entry_unfilled_falls_back_to_market_after_timeout():
    O, H, L, C = _flat()
    v = SimBarVenue(O, H, L, C, slippage_bps=1.0)
    ex = _ex(v)
    for t in range(1, 391):
        ex.step(t, C[t - 1], (lambda pos: 1) if t == 30 else ((lambda pos: pos) if t % 30 == 0 else None))
    kinds = [e[1:3] for e in ex.log]
    assert kinds[:3] == [("post", "entry"), ("cancel", "entry"), ("fill", "entry")]
    assert ex.log[1][0] == 35                                    # 5-minute timeout
    tr = ex.trades[0]
    assert not tr.entry_maker and tr.entry_bar == 35 and np.isclose(tr.entry_px, 100.0 * 1.0001)
    assert tr.exit_reason == "eod" and not tr.exit_maker and tr.exit_bar == 390   # flat market, EOD -> market
    assert tr.qty == 2.0


def test_maker_exit_then_flip_entry_next_minute():
    O, H, L, C = _flat()
    L[31] = 99.0                                       # buy limit 99.9 traded through on bar 31
    H[61] = 101.0                                      # sell (exit) limit 100.1 traded through on bar 61
    L[62] = 99.0                                       # ... flip entry (sent at 62) is never filled: sell at 100.1
    v = SimBarVenue(O, H, L, C, slippage_bps=1.0)
    ex = _ex(v)
    for t in range(1, 391):
        f = None
        if t == 30:
            f = lambda pos: 1
        elif t == 60:
            f = lambda pos: -1
        elif t % 30 == 0:
            f = lambda pos: pos
        ex.step(t, C[t - 1], f)
    first, second = ex.trades[:2]
    assert first.entry_maker and first.entry_bar == 31 and first.exit_reason == "flip" and first.exit_bar == 61
    assert second.side == -1 and second.entry_kind == "flip"
    post_flip = [e for e in ex.log if e[1] == "post" and e[2] == "entry"][1]
    assert post_flip[0] == 62                          # sent the minute after the maker exit fill
    assert not second.entry_maker and second.entry_bar == 67


def test_orders_resolve_by_the_next_decision():
    """Even with a long timeout an order never outlives the next decision (deadline)."""
    O, H, L, C = _flat()
    v = SimBarVenue(O, H, L, C, slippage_bps=1.0)
    ex = _ex(v, maker_timeout=60)
    ex.step(30, 100.0, lambda pos: 1)
    for t in range(31, 60):
        ex.step(t, 100.0)
    assert ex.working is not None
    ex.step(60, 100.0, lambda pos: pos)                 # timeout at the deadline runs first
    assert ex.working is None and ex.pos == 1 and ex.entry.bar == 60 and not ex.entry.maker
    from live_momentum.executor import _Order           # a stuck order must stop the decision
    ex.working = _Order("stuck", "exit", -1, 2.0, 100.1, 85, 10_000)
    with pytest.raises(RuntimeError):
        ex.step(90, 100.0, lambda pos: pos)


def test_only_maker_chase_supported():
    v = SimBarVenue(*_flat(), slippage_bps=1.0)
    with pytest.raises(ValueError):
        MakerChaseExecutor(v, backtest_config("BTCUSDT", entry_mode="taker"), np.arange(30, 390, 30), 390,
                           qty_fn=lambda t, last: 1.0)
