"""Phase 1 runtime: live Binance market data -> PaperTrader. Sends NO orders.

    python -m live_momentum.run_paper --config /etc/live_momentum/config.toml

Timeline per NYSE session (America/New_York):
    09:30:0x  bar 09:29 closed -> history (archive + collected bars) -> sizing (thread)
    every minute boundary + grace: wait for the closed kline of every symbol (REST repair
              if the stream missed it) -> PaperTrader.on_boundary
    16:00     session end -> funding of the day (REST) -> end_session summary
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

import pandas as pd

from crypto_intraday_momentum.data import load_funding, load_klines

from .bar_store import BarStore, merged_history
from .bars import ONE_MIN
from .binance_public import WS_MARKET, WS_PUBLIC, AccessRestricted, PublicRest, stream, ws_kline_row
from .config import load_config
from .history import prepare
from .paper import PaperTrader
from .persistence import EventLog
from .signal_engine import session_for
from .strategy import HISTORY_START, TICKS_RESEARCH

log = logging.getLogger("live_momentum")
GRACE_S = 1.0          # wait after the boundary before looking for the closed bar
BAR_WAIT_S = 4.0       # then wait up to this long for the stream before REST repair


def now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


class App:
    def __init__(self, cfg, equity: float):
        self.cfg = cfg
        self.data = Path(cfg.data_dir)
        self.rest = PublicRest()
        self.stores = {s: BarStore(self.data, s) for s in cfg.symbols}
        self.stop = asyncio.Event()
        self.equity = equity
        self.trader: PaperTrader | None = None
        self.preparing = False
        self.eventlog: EventLog | None = None
        self.open_retry_at = 0.0       # backoff after a failed session open
        self.open_backoff = 60.0

    # ---------------------------------------------------------------- setup
    def check_exchange(self):
        info = self.rest.exchange_info(self.cfg.symbols)
        for s in self.cfg.symbols:
            if s not in info or info[s]["status"] != "TRADING" or info[s]["contract"] != "PERPETUAL":
                raise SystemExit(f"{s}: not a trading perpetual: {info.get(s)}")
            if abs(info[s]["tick"] - TICKS_RESEARCH[s]) > 1e-12:
                log.warning("%s tick %s differs from the backtest tick %s", s, info[s]["tick"], TICKS_RESEARCH[s])
        return info

    def clock_offset_ms(self) -> float:
        t0 = time.time() * 1000
        srv = self.rest.server_time_ms()
        t1 = time.time() * 1000
        return (t0 + t1) / 2 - srv

    def backfill(self, since: pd.Timestamp):
        end = now_utc().floor("min")
        for s, st in self.stores.items():
            st.load(since)
            miss = st.missing(since, end)
            if miss:
                df = self.rest.klines(s, miss[0], end)
                st.add_frame(df)
                st.flush()
                log.info("%s backfilled %d bars", s, len(df))

    # ---------------------------------------------------------------- streams
    def on_market(self, name, d, recv_ms):
        sym = d.get("s")
        if d.get("e") == "kline" and d["k"].get("x"):
            ot, row = ws_kline_row(d["k"])
            self.stores[sym].add(ot, row)
            if self.trader:
                self.trader.on_bar(sym, ot, row)
        elif d.get("e") == "aggTrade" and self.trader:
            self.trader.on_trade(sym, float(d["p"]), float(d["q"]), int(d["T"]))

    def on_public(self, name, d, recv_ms):
        if d.get("e") == "bookTicker" and self.trader:
            self.trader.on_book(d["s"], float(d["b"]), float(d["a"]), float(d["B"]), float(d["A"]), int(d["T"]))

    def on_connect(self, url):
        log.info("connected %s", url)
        if self.eventlog:
            self.eventlog.write("ws_connect", url=url)

    # ---------------------------------------------------------------- session
    def _history(self, sess):
        month = sess.date.strftime("%Y-%m")
        bars, funding = {}, {}
        for s in self.cfg.symbols:
            arch = load_klines(s, HISTORY_START, month)
            st = self.stores[s]
            st.load(arch.index[-1])                           # collected bars on disk after the archive
            missing = st.missing(arch.index[-1] + ONE_MIN, sess.start)
            if missing:                                       # repair by REST before sizing
                st.add_frame(self.rest.klines(s, missing[0], sess.start))
                st.flush()
            bars[s] = merged_history(arch, st.frame(arch.index[-1] + ONE_MIN))
            f = load_funding(s, HISTORY_START, month)
            since = f["time"].max() if len(f) else pd.Timestamp(HISTORY_START + "-01", tz="UTC")
            recent = self.rest.funding(s, since + pd.Timedelta(minutes=1))
            funding[s] = pd.concat([f, recent]).drop_duplicates("time").sort_values("time").reset_index(drop=True)
        return bars, funding

    async def open_session(self, sess, exch):
        self.preparing = True
        try:
            day_dir = self.data / "paper" / f"{sess.date:%Y-%m-%d}"
            self.eventlog = EventLog(day_dir / "events.jsonl")
            bars, funding = await asyncio.to_thread(self._history, sess)
            prep = await asyncio.to_thread(prepare, sess, bars, funding, {s: exch[s]["tick"] for s in exch})
            tr = PaperTrader(self.cfg, exch, lambda: int(time.time() * 1000), self.eventlog,
                             Path(self.cfg.state_dir) / "paper_state.json", self.equity_now())
            if not tr.restore(prep):
                tr.start_session(prep)
            self.trader = tr
            self.open_backoff = 60.0
        except Exception as e:
            log.exception("session open failed; retry in %.0f s", self.open_backoff)
            if self.eventlog is not None:
                self.eventlog.write("open_failed", error=repr(e)[:500], retry_sec=self.open_backoff)
            self.open_retry_at = time.time() + self.open_backoff
            self.open_backoff = min(self.open_backoff * 2, 900.0)
        finally:
            self.preparing = False

    def equity_now(self) -> float:
        from .persistence import read_json
        st = read_json(Path(self.cfg.state_dir) / "paper_equity.json")
        return float(st["equity"]) if st else self.equity

    def close_session(self, sess):
        from .persistence import atomic_write_json, read_json
        fr = {}
        for s in self.cfg.symbols:
            try:
                fr[s] = self.rest.funding(s, sess.start - pd.Timedelta(hours=1))
            except Exception as e:      # noqa: BLE001
                log.warning("funding fetch failed for %s: %s", s, e)
        summary = self.trader.end_session(fr)
        path = Path(self.cfg.state_dir) / "paper_equity.json"
        hist = (read_json(path) or {}).get("history", [])
        hist.append(summary)
        atomic_write_json(path, {"equity": summary["equity_close"], "history": hist})
        log.info("session %s closed: pnl %.2f (%.3f%%), %d trades", summary["date"], summary["pnl"],
                 summary["ret"] * 100, summary["n_trades"])
        self.trader = None

    # ---------------------------------------------------------------- clock
    async def ensure_bar(self, k: pd.Timestamp):
        deadline = time.monotonic() + BAR_WAIT_S
        while time.monotonic() < deadline and not all(st.has(k) for st in self.stores.values()):
            await asyncio.sleep(0.2)
        for s, st in self.stores.items():
            if not st.has(k):
                df = await asyncio.to_thread(self.rest.klines, s, k - 5 * ONE_MIN, k + ONE_MIN)
                st.add_frame(df)
                if self.trader:
                    for ot, r in df.iterrows():
                        self.trader.on_bar(s, ot, r.to_dict())
                if self.eventlog:
                    self.eventlog.write("bar_repair", sym=s, bar=str(k), ok=st.has(k))

    async def clock(self, exch):
        last_offset_check = 0.0
        while not self.stop.is_set():
            now = now_utc()
            nxt = now.floor("min") + ONE_MIN
            await asyncio.sleep((nxt - now).total_seconds() + GRACE_S)
            await self.ensure_bar(nxt - ONE_MIN)
            for st in self.stores.values():
                st.flush()
                st.prune(nxt - pd.Timedelta(days=50))
            if time.monotonic() - last_offset_check > 3600:
                off = await asyncio.to_thread(self.clock_offset_ms)
                last_offset_check = time.monotonic()
                log.info("clock offset vs exchange: %.0f ms", off)
                if self.trader and self.trader.risk:
                    self.trader.risk.clock_offset_ms = off
            sess = session_for(nxt.tz_convert("America/New_York").tz_localize(None))
            if sess is None:
                continue
            if (self.trader is None and not self.preparing and time.time() >= self.open_retry_at
                    and sess.start < nxt < sess.end):
                asyncio.create_task(self.open_session(sess, exch))
                continue
            if self.trader is not None and self.trader.prep.session == sess:
                tr = self.trader
                if not tr.finished:
                    missed = {}
                    if sess.minute(nxt) > tr.last_t + 1:
                        missed = {s: st.frame(sess.start) for s, st in self.stores.items()}
                    tr.on_boundary(nxt, missed)
                if tr.finished and not tr.closed and nxt >= sess.end:
                    await asyncio.to_thread(self.close_session, sess)

    # ---------------------------------------------------------------- main
    async def run(self):
        exch = self.check_exchange()
        off = self.clock_offset_ms()
        log.info("clock offset vs exchange: %.0f ms", off)
        if abs(off) > 1000:
            log.error("local clock is %.0f ms off the exchange: fix chrony before trading", off)
        self.backfill(now_utc().floor("min") - pd.Timedelta(days=3))
        syms = [s.lower() for s in self.cfg.symbols]
        tasks = [
            asyncio.create_task(stream(WS_MARKET, [f"{s}@kline_1m" for s in syms] + [f"{s}@aggTrade" for s in syms],
                                       self.on_market, self.stop, self.on_connect)),
            asyncio.create_task(stream(WS_PUBLIC, [f"{s}@bookTicker" for s in syms], self.on_public,
                                       self.stop, self.on_connect)),
            asyncio.create_task(self.clock(exch)),
        ]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            if t.exception():
                self.stop.set()
                raise t.exception()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--equity", type=float, default=10_000.0, help="initial paper equity (USDT)")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if cfg.mode != "paper" or not cfg.dry_run:
        raise SystemExit("run_paper requires mode='paper' and dry_run=true")
    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(Path(cfg.log_dir) / "paper.log")])
    try:
        asyncio.run(App(cfg, a.equity).run())
    except AccessRestricted as e:
        log.error("%s", e)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
