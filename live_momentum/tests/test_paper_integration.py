"""Phase 1 integration: PaperTrader driven by a fake feed (clock, trade tape, book).

The fake tape is generated from 1m bars (open at +0.1 s, low at +20 s, high at +40 s, close at
+59 s) and the book quotes the bar open +/- 1 bp. Under these conditions the tape venue's fill
rule is the backtest rule, so the paper trades must equal replay_session exactly - including
after a restart in the middle of the session (state restore + catch-up).
"""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.sessions import US, build_sessions
from live_momentum.config import LiveConfig, RiskLimits
from live_momentum.history import prepare
from live_momentum.paper import PaperTrader
from live_momentum.persistence import EventLog
from live_momentum.replay import replay_session
from live_momentum.signal_engine import session_for
from live_momentum.sizing_live import session_sizing
from live_momentum.strategy import backtest_config

SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
EXCH = {s: dict(tick=0.1, step=1e-6, market_step=1e-6, min_notional=0.0) for s in SYMS}
COLS = ["side", "entry_bar", "exit_bar", "entry_px", "exit_px", "entry_maker", "exit_maker", "exit_reason",
        "dec_j", "entry_kind"]


class Clock:
    def __init__(self):
        self.ms = 0

    def __call__(self):
        return self.ms

    def set(self, ts: pd.Timestamp, plus_s: float = 0.0):
        self.ms = int(ts.value // 1_000_000 + plus_s * 1000)


def _cfg(tmp_path, **risk):
    kw = dict(max_gross_leverage=3.0, daily_max_loss_pct=0.19, kill_switch_file=str(tmp_path / "KILL"))
    kw.update(risk)
    return LiveConfig(mode="paper", dry_run=True, risk=RiskLimits(**kw)).validate()


def _bars(df, sess):
    return df.loc[sess.start: sess.end - pd.Timedelta(minutes=1)]


def drive(tr: PaperTrader, clock: Clock, dfs: dict, sess, t_from=1, t_to=None, hooks=None):
    """Feed minutes t_from..t_to: tape of bar t-1 has been delivered before boundary t."""
    n = sess.n_min
    t_to = t_to or n
    bars = {s: _bars(df, sess) for s, df in dfs.items()}
    for t in range(t_from, t_to + 1):
        T = sess.start + pd.Timedelta(minutes=t)
        for s, b in bars.items():
            o = b["open"].iloc[t] if t < n else b["close"].iloc[n - 1]
            clock.set(T, 0.1)
            if t < n:
                tr.on_trade(s, o, 1.0, clock.ms)
            tr.on_book(s, o * (1.0 - 1e-4), o * (1.0 + 1e-4), 5.0, 5.0, clock.ms)
            k = b.index[t - 1]
            tr.on_bar(s, k, b.iloc[t - 1].to_dict())
        clock.set(T, 1.0)
        if hooks and t in hooks:
            hooks[t]()
        tr.on_boundary(T)
        if t < n:
            for s, b in bars.items():
                r = b.iloc[t]
                for dt_, px in ((20, r["low"]), (40, r["high"]), (59, r["close"])):
                    clock.set(T, dt_)
                    tr.on_trade(s, px, 1.0, clock.ms)


@pytest.fixture(scope="module")
def setup(synth_portfolio_dfs):
    dfs = synth_portfolio_dfs
    m = build_sessions(dfs["BTCUSDT"], US)
    # a late session where every symbol trades in the backtest replay
    for day in m.dates[::-1][:30]:
        reps = {s: replay_session(df, day, backtest_config(s, tick=0.1, include_funding=False))[0] for s, df in dfs.items()}
        if all(len(r) for r in reps.values()) and sum(len(r) for r in reps.values()) >= 4:
            break
    sess = session_for(day)
    prep = prepare(sess, dfs, {}, {s: 0.1 for s in SYMS})
    return dfs, sess, prep, reps


def _trader(tmp_path, prep, clock, **risk):
    prep = dataclasses.replace(prep, sizing=dataclasses.replace(
        prep.sizing, g=1.0, eff={s: 0.5 for s in SYMS}))           # keep the gross-leverage cap slack
    tr = PaperTrader(_cfg(tmp_path, **risk), EXCH, clock, EventLog(tmp_path / "events.jsonl", clock),
                     tmp_path / "state.json", equity=10_000.0)
    return tr, prep


def _paper_trades(tr, sym):
    return pd.DataFrame([dataclasses.asdict(r) for r in tr.books[sym].ex.trades])


def _expected(reps, sess, sym):
    r = reps[sym]
    out = r.copy()
    out["entry_bar"] = ((r["entry_time"] - sess.start) // pd.Timedelta(minutes=1)).astype(int)
    out["exit_bar"] = out["entry_bar"] + r["hold_min"]
    return out


def test_prepare_matches_session_sizing(setup):
    from live_momentum.sizing_live import SessionSizing
    from crypto_intraday_momentum.signals import compute_signals
    from crypto_intraday_momentum.sizing import pre_open_rv, unit_trades
    dfs, sess, prep, _ = setup
    data = {}
    for s, df in dfs.items():
        m = build_sessions(df, US)
        data[s] = (m, unit_trades(m, compute_signals(m), backtest_config(s, tick=0.1, include_funding=False)),
                   pre_open_rv(df, m))
    ref = session_sizing(data, sess.date)
    assert prep.sizing.g == ref.g and np.isclose(prep.sizing.scale, ref.scale, rtol=1e-12)
    for s in SYMS:
        assert np.isclose(prep.sizing.eff[s], ref.eff[s], rtol=1e-12)


def test_prepare_refuses_history_gap(setup):
    from live_momentum.signal_engine import DataGap
    dfs, sess, _, _ = setup
    cut = {s: df[df.index < sess.start - pd.Timedelta(hours=6)] for s, df in dfs.items()}
    with pytest.raises(DataGap):
        prepare(sess, cut, {}, {s: 0.1 for s in SYMS})


def test_paper_equals_backtest_replay(setup, tmp_path):
    dfs, sess, prep, reps = setup
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess)
    for s in SYMS:
        got = _paper_trades(tr, s)
        exp = _expected(reps, sess, s)
        assert len(got) == len(exp), s
        pd.testing.assert_frame_equal(got[COLS].reset_index(drop=True), exp[COLS].reset_index(drop=True),
                                      check_dtype=False, obj=s)
        # quantity = equity * multiplier / last price at the send, constant per position
        assert (got["qty"] > 0).all()
    summary = tr.end_session({})
    assert summary["n_trades"] == sum(len(r) for r in reps.values())
    ev = EventLog(tmp_path / "events.jsonl").read()
    kinds = {e["type"] for e in ev}
    assert {"session_start", "decision", "order_post", "order_fill", "session_end"} <= kinds
    assert not any(e["type"] == "risk_entry" for e in ev)


def test_paper_market_fallbacks_equal_backtest(setup, tmp_path):
    """Large tick -> limits far from the market -> timeouts -> market orders at the book."""
    dfs, sess, prep, _ = setup
    tick = 40.0
    reps = {s: replay_session(df, sess.date, backtest_config(s, tick=tick, include_funding=False))[0]
            for s, df in dfs.items()}
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock)
    tr.exch = {s: dict(EXCH[s], tick=tick) for s in SYMS}
    tr.start_session(prep)
    drive(tr, clock, dfs, sess)
    n_taker = 0
    for s in SYMS:
        got, exp = _paper_trades(tr, s), _expected(reps, sess, s)
        pd.testing.assert_frame_equal(got[COLS].reset_index(drop=True), exp[COLS].reset_index(drop=True),
                                      check_dtype=False, obj=s)
        n_taker += int((~got["entry_maker"]).sum() + (~got["exit_maker"]).sum())
    assert n_taker >= 2


def test_restart_mid_session_gives_same_trades(setup, tmp_path):
    dfs, sess, prep, reps = setup
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess, 1, 150)
    # process dies; a new one starts 25 minutes later
    tr2, _ = _trader(tmp_path, prep, clock)
    assert tr2.restore(prep) and tr2.last_t == 150
    missed = {s: _bars(df, sess) for s, df in dfs.items()}
    T = sess.start + pd.Timedelta(minutes=176)
    clock.set(T, 1.0)
    tr2.on_boundary(T, {s: x[x.index < T] for s, x in missed.items()})
    drive(tr2, clock, dfs, sess, 177)
    for s in SYMS:
        got, exp = _paper_trades(tr2, s), _expected(reps, sess, s)
        pd.testing.assert_frame_equal(got[COLS].reset_index(drop=True), exp[COLS].reset_index(drop=True),
                                      check_dtype=False, obj=s)


def test_kill_switch_flattens_and_blocks(setup, tmp_path):
    dfs, sess, prep, reps = setup
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock)
    tr.start_session(prep)
    first_entry = min(_expected(reps, sess, s)["entry_bar"].min() for s in SYMS)
    t_kill = first_entry + 2
    drive(tr, clock, dfs, sess, hooks={t_kill: lambda: (tmp_path / "KILL").write_text("x")})
    trades = pd.concat([_paper_trades(tr, s) for s in SYMS])
    assert (trades["exit_reason"] == "kill").sum() >= 1
    assert (trades["exit_bar"] == t_kill)[trades["exit_reason"] == "kill"].all()
    assert (trades["entry_bar"] < t_kill).all()                       # nothing opened afterwards
    assert all(b.ex.pos == 0 for b in tr.books.values())
    assert tr.risk.halted == "kill_switch"


def test_daily_loss_limit_flattens(setup, tmp_path):
    dfs, sess, prep, reps = setup
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock, daily_max_loss_pct=1e-6)   # any fee breaches it
    tr.start_session(prep)
    drive(tr, clock, dfs, sess)
    trades = pd.concat([_paper_trades(tr, s) for s in SYMS])
    assert tr.risk.halted == "daily_loss"
    assert (trades["exit_reason"] == "daily_loss").any()
    n_before = len(trades)
    assert n_before < sum(len(r) for r in reps.values()) or (trades["exit_reason"] == "daily_loss").all()


def test_stale_data_blocks_entries(setup, tmp_path):
    dfs, sess, prep, reps = setup
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock, stale_data_sec=0.5)      # boundary runs 0.9 s after data
    tr.start_session(prep)
    drive(tr, clock, dfs, sess)
    assert all(len(b.ex.trades) == 0 and b.ex.pos == 0 for b in tr.books.values())
    ev = EventLog(tmp_path / "events.jsonl").read()
    assert any(e["type"] == "risk_entry" and e["reason"] == "stale_data" for e in ev)


def test_paper_requires_paper_mode(tmp_path):
    with pytest.raises(ValueError):
        PaperTrader(LiveConfig(), EXCH, Clock(), EventLog(tmp_path / "e.jsonl"), tmp_path / "s.json", 1.0)


def test_daily_report_three_views_agree(setup, tmp_path):
    """Run the paper session, store the 'collected' bars and an 'archive', build the report."""
    from live_momentum.bar_store import BarStore
    from live_momentum.paper_report import build_report, to_markdown
    dfs, sess, prep, reps = setup
    data_dir = tmp_path / "data"
    clock = Clock()
    log = EventLog(data_dir / "paper" / f"{sess.date:%Y-%m-%d}" / "events.jsonl", clock)
    p2 = dataclasses.replace(prep, sizing=dataclasses.replace(prep.sizing, g=1.0, eff={s: 0.5 for s in SYMS}))
    tr = PaperTrader(_cfg(tmp_path), EXCH, clock, log, tmp_path / "state.json", equity=10_000.0)
    tr.start_session(p2)
    drive(tr, clock, dfs, sess)
    tr.end_session({})
    cache = tmp_path / "cache"
    for s, df in dfs.items():
        st = BarStore(data_dir, s)
        st.add_frame(_bars(df, sess))                       # bars "collected live" for the session
        st.flush()
        raw = df.drop(columns="filled").reset_index()
        for mth, part in raw.groupby(raw["open_time"].dt.strftime("%Y-%m")):
            d = cache / "klines_v2" / s
            d.mkdir(parents=True, exist_ok=True)
            part.to_parquet(d / f"{s}-1m-{mth}.parquet", index=False)
    r = build_report(data_dir, sess.date, archive_cache=cache)
    assert not r["issues"], r["issues"]
    for s, x in r["symbols"].items():
        assert x["same_trades_as_replay_live"] is True
        assert x["trades"]["paper"] == x["trades"]["replay_live"] == x["trades"]["replay_arch"] == len(reps[s])
        assert x["bars_live_vs_archive"]["missing_live"] == 0 and x["bars_live_vs_archive"]["close_mismatch"] == 0
        assert np.isclose(x["ret_pct"]["replay_live"], x["ret_pct"]["replay_arch"])
        # paper P&L uses the real quantity (equity * multiplier / last at the send)
        assert np.isclose(x["ret_pct"]["paper"], x["ret_pct"]["replay_live"], rtol=2e-2, atol=1e-4)
    md = to_markdown(r)
    assert "| BTCUSDT |" in md and "replay on archive" in md


def test_restore_persists_restored_state_immediately(setup, tmp_path):
    """A crash right after restore() must not leave start_session()'s fresh state on disk."""
    from live_momentum.persistence import read_json
    dfs, sess, prep, _ = setup
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess, 1, 150)
    n_trades = {s: len(tr.books[s].ex.trades) for s in SYMS}
    tr2, _ = _trader(tmp_path, prep, clock)
    assert tr2.restore(prep)
    assert read_json(tmp_path / "state.json")["last_t"] == 150
    tr3, _ = _trader(tmp_path, prep, clock)          # second crash before any boundary
    assert tr3.restore(prep) and tr3.last_t == 150
    assert {s: len(tr3.books[s].ex.trades) for s in SYMS} == n_trades


def test_funding_uses_close_of_bar_ending_at_settlement(setup, tmp_path):
    dfs, sess, prep, _ = setup
    clock = Clock()
    tr, prep = _trader(tmp_path, prep, clock)
    tr.start_session(prep)
    drive(tr, clock, dfs, sess)
    sym = next(s for s in SYMS if tr.books[s].ex.trades)
    r = tr.books[sym].ex.trades[0]
    f = sess.start + (r.entry_bar + 1) * pd.Timedelta(minutes=1)
    assert r.exit_bar > r.entry_bar + 1
    fund = {sym: pd.DataFrame({"time": [f], "rate": [1e-4]})}
    tr.end_session(fund)
    end = next(e for e in EventLog(tmp_path / "events.jsonl").read() if e["type"] == "session_end")
    row = next(x for x in end["trades"] if x["sym"] == sym and x["entry_bar"] == r.entry_bar)
    px = tr.books[sym].today[f - pd.Timedelta(minutes=1)]["close"]
    assert row["funding"] == pytest.approx(r.side * r.qty * px * 1e-4)
