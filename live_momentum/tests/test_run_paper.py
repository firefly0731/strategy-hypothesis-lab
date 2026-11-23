"""run_paper.App: region restriction during the session open stops the app (no retry)."""
import asyncio

import pandas as pd
import pytest

from live_momentum import run_paper
from live_momentum.binance_public import AccessRestricted
from live_momentum.config import load_config
from live_momentum.signal_engine import session_for


def cfg(tmp_path):
    p = tmp_path / "c.toml"
    root = tmp_path.as_posix()
    p.write_text(f'''mode = "paper"
dry_run = true
data_dir = "{root}/data"
state_dir = "{root}/state"
log_dir = "{root}/log"
[risk]
daily_max_loss_pct = 0.03
max_notional_per_symbol = 0.0
max_gross_leverage = 3.0
stale_data_sec = 10.0
kill_switch_file = "{root}/KILL"
''', encoding="utf-8")
    return load_config(p)


def test_access_restricted_in_session_open_stops(tmp_path, monkeypatch):
    app = run_paper.App(cfg(tmp_path), 10_000.0)

    def blocked(sess):
        raise AccessRestricted("HTTP 451")
    monkeypatch.setattr(app, "_history", blocked)
    sess = session_for(pd.Timestamp("2024-04-17"))
    asyncio.run(app.open_session(sess, {}))
    assert isinstance(app.fatal, AccessRestricted) and app.stop.is_set()
    assert app.trader is None and app.open_retry_at == 0.0     # no retry scheduled

    async def clock_once():
        monkeypatch.setattr(run_paper, "GRACE_S", 0.0)
        monkeypatch.setattr(app, "stop", asyncio.Event())    # clock must stop on fatal, not on stop
        real_sleep = asyncio.sleep
        monkeypatch.setattr(run_paper.asyncio, "sleep", lambda s: real_sleep(0))
        await app.clock({})
    with pytest.raises(AccessRestricted):
        asyncio.run(clock_once())


def test_other_errors_in_session_open_retry_with_backoff(tmp_path, monkeypatch):
    app = run_paper.App(cfg(tmp_path), 10_000.0)
    monkeypatch.setattr(app, "_history", lambda sess: (_ for _ in ()).throw(RuntimeError("boom")))
    sess = session_for(pd.Timestamp("2024-04-17"))
    asyncio.run(app.open_session(sess, {}))
    assert app.fatal is None and not app.stop.is_set()
    assert app.open_retry_at > 0 and app.open_backoff == 120.0


@pytest.mark.parametrize("book", [True, False])
def test_book_stream_subscription_is_optional(tmp_path, monkeypatch, book):
    """Paper subscribes bookTicker (maker-fill simulation); live does not (BOOK_STREAM=False)."""
    from live_momentum import run_live
    assert run_paper.App.BOOK_STREAM is True and run_live.LiveApp.BOOK_STREAM is False
    app = run_paper.App(cfg(tmp_path), 10_000.0)
    app.BOOK_STREAM = book
    urls = []

    async def fake_stream(url, streams, *a, **k):
        urls.append((url, tuple(streams)))
        await asyncio.Event().wait()

    monkeypatch.setattr(run_paper, "stream", fake_stream)
    monkeypatch.setattr(app, "check_exchange", lambda: {})
    monkeypatch.setattr(app, "clock_offset_ms", lambda: 0.0)
    monkeypatch.setattr(app, "backfill", lambda start: None)

    class Done(Exception):
        pass

    async def clock(exch):
        for _ in range(3):
            await asyncio.sleep(0)
        raise Done
    monkeypatch.setattr(app, "clock", clock)
    with pytest.raises(Done):
        asyncio.run(app.run())
    got = {u for u, _ in urls}
    assert run_paper.WS_MARKET in got
    assert (run_paper.WS_PUBLIC in got) is book
    assert not any("bookTicker" in s for u, ss in urls if u == run_paper.WS_MARKET for s in ss)
