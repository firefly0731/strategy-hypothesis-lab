"""Phase 1 paper trader: live data -> signals -> virtual orders on the live tape. No orders.

Synchronous and event driven so it can be tested with a fake clock and a fake feed:

    on_trade / on_book / on_bar   market data (from the WebSocket layer)
    start_session(prepared)       at the open (sizing computed by history.prepare)
    on_boundary(now)              once per minute boundary, after bar now-1min has closed
    end_session(funding_rates)    after 16:00 NY

State is written after every boundary; `restore` + catch-up continue a session after a restart.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .bar_store import COLS
from .bars import ONE_MIN, regularize
from .config import LiveConfig
from .executor import MakerChaseExecutor, _jsonable
from .history import Prepared
from .persistence import EventLog, atomic_write_json, read_json
from .replay import rules_from
from .risk import RiskManager
from .signal_engine import DataGap, snapshot, target_position
from .strategy import backtest_config
from .tape_venue import TapeVenue

FUNDING_HOURS_UTC = (0, 8, 16)


@dataclass
class SymbolBook:
    sym: str
    ex: MakerChaseExecutor
    venue: TapeVenue
    history: pd.DataFrame                 # regular frame, bars before the open (window)
    today: dict = field(default_factory=dict)   # open_time -> row (closed bars of the session)
    last_msg_ms: int = 0
    gaps: int = 0


def floor_step(qty: float, step: float) -> float:
    return math.floor(qty / step + 1e-9) * step if step > 0 else qty


class PaperTrader:
    def __init__(self, cfg: LiveConfig, exch: dict, clock_ms, log: EventLog, state_path: Path,
                 equity: float, history_days: int = 45):
        if cfg.mode != "paper" or not cfg.dry_run:
            raise ValueError("PaperTrader requires mode='paper' and dry_run=true")
        self.cfg, self.exch, self.clock_ms, self.log = cfg, exch, clock_ms, log
        self.state_path = Path(state_path)
        self.equity = equity
        self.history_days = history_days
        self.books: dict[str, SymbolBook] = {}
        self.prep: Prepared | None = None
        self.risk: RiskManager | None = None
        self.last_t = 0
        self.finished = False
        self.closed = False          # end_session done (equity booked)
        self.last_px: dict[str, float] = {}

    # ------------------------------------------------------------------ market data
    def on_trade(self, sym, price, qty, ts):
        b = self.books.get(sym)
        self.last_px[sym] = price
        if b:
            b.venue.on_trade(price, qty, ts)
            b.last_msg_ms = self.clock_ms()

    def on_book(self, sym, bid, ask, bid_qty, ask_qty, ts):
        b = self.books.get(sym)
        if b:
            b.venue.on_book(bid, ask, bid_qty, ask_qty, ts)
            b.last_msg_ms = self.clock_ms()

    def on_bar(self, sym, open_time: pd.Timestamp, row: dict):
        b = self.books.get(sym)
        if b and self.prep and self.prep.session.start <= open_time < self.prep.session.end:
            b.today[open_time] = {c: row[c] for c in COLS}
        self.last_px.setdefault(sym, row["close"])

    # ------------------------------------------------------------------ session lifecycle
    def start_session(self, prep: Prepared) -> None:
        sess = prep.session
        self.prep, self.last_t, self.finished, self.closed = prep, 0, False, False
        self.risk = RiskManager(self.cfg.risk, self.equity)
        start_ms = int(sess.start.value // 1_000_000)
        dec_min = None
        self.books = {}
        for sym in self.cfg.symbols:
            info = self.exch[sym]
            cfg = backtest_config(sym, tick=info["tick"])
            venue = TapeVenue(start_ms, self.clock_ms)
            hist = prep.history[sym]
            hist = hist[hist.index >= sess.start - pd.Timedelta(days=self.history_days)]
            from crypto_intraday_momentum.signals import decision_minutes
            dec_min = decision_minutes(sess.n_min)
            ex = MakerChaseExecutor(venue, cfg, dec_min, sess.n_min,
                                    qty_fn=self._qty_fn(sym), gate=self._gate(sym),
                                    cid_prefix=f"lm{sess.date:%y%m%d}{sym[:3]}",
                                    listener=self._listener(sym))
            self.books[sym] = SymbolBook(sym, ex, venue, hist)
        sz = prep.sizing
        self.log.write("session_start", date=str(sess.date.date()), start=str(sess.start),
                       equity_open=self.equity, g=sz.g, dd=sz.dd, scale=sz.scale,
                       eff=sz.eff, lev=sz.lev, multiplier={s: sz.multiplier(s) for s in self.cfg.symbols},
                       ticks={s: self.exch[s]["tick"] for s in self.cfg.symbols})
        self.save()

    def _qty_fn(self, sym):
        def f(t, last):
            mult = self.prep.sizing.multiplier(sym)
            info = self.exch[sym]
            q = floor_step(self.risk.equity_open * mult / last, info["step"])
            if q * last < info["min_notional"]:
                self.log.write("entry_too_small", sym=sym, t=t, qty=q, notional=q * last,
                               min_notional=info["min_notional"])
                return 0.0
            return q
        return f

    def _gate(self, sym):
        def g(t, side, qty):
            b = self.books[sym]
            age = (self.clock_ms() - b.last_msg_ms) / 1000.0 if b.last_msg_ms else float("inf")
            px = self.last_px.get(sym, np.nan)
            q, why = self.risk.approve_entry(sym, side, qty, px, self.open_notional(), age)
            q = floor_step(q, self.exch[sym]["step"])
            if why:
                self.log.write("risk_entry", sym=sym, t=t, side=side, asked=qty, approved=q, reason=why)
            return q
        return g

    def _listener(self, sym):
        def on(ev):
            t, kind, what, side, px, extra = ev
            self.log.write("order_" + kind, sym=sym, t=t, leg=what, side=side, px=px, info=extra)
        return on

    def open_notional(self) -> dict:
        return {s: b.ex.pos * b.ex.qty * self.last_px.get(s, np.nan) for s, b in self.books.items() if b.ex.pos}

    # ------------------------------------------------------------------ P&L
    def fee(self, px, qty, maker):
        c = backtest_config("BTCUSDT")
        return px * qty * (c.maker_fee if maker else c.taker_fee)

    def pnl_today(self) -> float:
        total = 0.0
        for s, b in self.books.items():
            for r in b.ex.trades:
                total += r.side * r.qty * (r.exit_px - r.entry_px) - self.fee(r.entry_px, r.qty, r.entry_maker) \
                    - self.fee(r.exit_px, r.qty, r.exit_maker)
            if b.ex.pos:
                e = b.ex.entry
                total += b.ex.pos * b.ex.qty * (self.last_px.get(s, e.price) - e.price) - self.fee(e.price, e.qty, e.maker)
        return total

    # ------------------------------------------------------------------ the minute boundary
    def _frame(self, b: SymbolBook) -> pd.DataFrame:
        if not b.today:
            return b.history
        today = pd.DataFrame.from_dict(b.today, orient="index")[COLS].sort_index()
        today.index.name = "open_time"
        return regularize(pd.concat([b.history[COLS], today])).assign(
            filled=lambda d: d["filled"] | d.index.isin(b.history.index[b.history["filled"]]))

    def on_boundary(self, now: pd.Timestamp, catchup_bars: dict | None = None) -> None:
        """Run minute boundary `now`. If boundaries were missed (restart), catch them up first
        using `catchup_bars` (sym -> frame with the missed session bars) and the bar fill rule."""
        if self.prep is None or self.finished:
            return
        sess = self.prep.session
        t = sess.minute(now)
        if t <= self.last_t or t < 1:
            return
        if t > self.last_t + 1:
            self._catch_up(t, catchup_bars or {})
        self._boundary(t, now)
        if t >= sess.n_min:
            self.finished = True
        self.save()

    def _catch_up(self, t_now: int, bars: dict) -> None:
        sess = self.prep.session
        self.log.write("catchup_start", from_t=self.last_t + 1, to_t=t_now - 1)
        for sym, df in bars.items():
            for ts, r in df.iterrows():
                if sess.start <= ts < sess.end:
                    self.books[sym].today[ts] = {c: r[c] for c in COLS}
        for tt in range(self.last_t + 1, t_now):
            for sym, b in self.books.items():
                k = sess.start + (tt - 1) * ONE_MIN
                row = b.today.get(k)
                if row is not None:
                    b.venue.on_bar_catchup(tt - 1, row["low"], row["high"])
                    nxt = b.today.get(k + ONE_MIN)          # backtest market rule: next bar open
                    if nxt is not None:
                        b.venue.on_book(nxt["open"] * (1 - 1e-4), nxt["open"] * (1 + 1e-4), np.nan, np.nan,
                                        self.clock_ms())
            self._boundary(tt, sess.start + tt * ONE_MIN, catchup=True)

    def _boundary(self, t: int, now: pd.Timestamp, catchup: bool = False) -> None:
        sess = self.prep.session
        # kill switch and daily loss: flatten first, then nothing new
        if self.risk.kill_requested():
            if self.risk.halted != "kill_switch":
                self.risk.halted = None
                self.risk.halt("kill_switch")
                self.log.write("kill_switch", t=t)
            for b in self.books.values():
                b.ex.flatten(t, "kill")
        elif self.risk.check_loss(self.pnl_today()):
            if any(b.ex.pos or b.ex.working for b in self.books.values()):
                self.log.write("daily_loss_flatten", t=t, pnl=self.pnl_today(), equity_open=self.risk.equity_open)
            for b in self.books.values():
                b.ex.flatten(t, "daily_loss")
        if now.hour in FUNDING_HOURS_UTC and now.minute == 0:
            self.log.write("funding_position", t=t, time=str(now),
                           pos={s: b.ex.pos * b.ex.qty for s, b in self.books.items()},
                           px={s: self.last_px.get(s) for s in self.books})
        for sym, b in self.books.items():
            want_fn, last = None, None
            k = now - ONE_MIN
            row = b.today.get(k)
            last = row["close"] if row else self.last_px.get(sym)
            is_dec = bool(np.any(b.ex.dec_min == t))
            if is_dec:
                try:
                    snap = snapshot(self._frame(b), now, history_days=self.history_days)
                except DataGap as e:
                    b.gaps += 1
                    self.log.write("data_gap", sym=sym, t=t, error=str(e))
                    snap = None
                if snap is not None and snap.ready:
                    j = snap.j()
                    rules = rules_from(b.ex.cfg)
                    def want_fn(pos, s=snap, j=j, sym=sym, t=t):
                        w = target_position(pos, s.px[j], s.ub[j], s.lb[j], s.vwap[j], s.sigma[j], s.t, rules)
                        self.log.write("decision", sym=sym, t=t, j=j, px=s.px[j], ub=s.ub[j], lb=s.lb[j],
                                       vwap=s.vwap[j], sigma=s.sigma[j], pos=pos, want=w, catchup=catchup)
                        return w
                elif snap is not None:
                    self.log.write("not_ready", sym=sym, t=t, n_prior=snap.n_prior)
            if last is None:
                self.log.write("no_price", sym=sym, t=t)
                continue
            b.ex.step(t, float(last), want_fn)
        self.last_t = t

    # ------------------------------------------------------------------ end of day
    def end_session(self, funding: dict[str, pd.DataFrame] | None = None) -> dict:
        """Close the day's books: realised P&L, fees, funding on positions held through a settlement."""
        sess = self.prep.session
        rows, fees, fund = [], 0.0, 0.0
        for sym, b in self.books.items():
            for r in b.ex.trades:
                f = self.fee(r.entry_px, r.qty, r.entry_maker) + self.fee(r.exit_px, r.qty, r.exit_maker)
                fc = 0.0
                fr = funding.get(sym) if funding else None
                if fr is not None and len(fr):
                    a, z = sess.start + r.entry_bar * ONE_MIN, sess.start + r.exit_bar * ONE_MIN
                    for _, x in fr[(fr["time"] > a) & (fr["time"] <= z)].iterrows():
                        bar = b.today.get(pd.Timestamp(x["time"]) - ONE_MIN)   # bar closing at the settlement
                        px = bar["close"] if bar else self.last_px.get(sym, r.exit_px)
                        fc += r.side * r.qty * px * x["rate"]
                gross = r.side * r.qty * (r.exit_px - r.entry_px)
                rows.append(dict(sym=sym, **asdict(r), gross=gross, fees=f, funding=fc, pnl=gross - f - fc))
                fees += f
                fund += fc
        pnl = sum(x["pnl"] for x in rows)
        eq0 = self.risk.equity_open
        self.equity = eq0 + pnl
        summary = dict(date=str(sess.date.date()), equity_open=eq0, equity_close=self.equity, pnl=pnl,
                       ret=pnl / eq0, fees=fees, funding=fund, n_trades=len(rows),
                       halted=self.risk.halted, gaps={s: b.gaps for s, b in self.books.items()})
        self.log.write("session_end", **summary, trades=rows,
                       venue={s: {"events": b.venue.events, "orders": [asdict(r) for r in b.venue.history]}
                              for s, b in self.books.items()})
        self.finished = self.closed = True
        self.save()
        return summary

    # ------------------------------------------------------------------ persistence
    def save(self) -> None:
        if self.prep is None:
            return
        sz = self.prep.sizing
        atomic_write_json(self.state_path, _jsonable(dict(
            date=str(self.prep.session.date.date()), last_t=self.last_t, finished=self.finished,
            closed=self.closed,
            equity=self.equity, equity_open=self.risk.equity_open, halted=self.risk.halted,
            sizing=dict(g=sz.g, dd=sz.dd, scale=sz.scale, weight=sz.weight, lev=sz.lev, eff=sz.eff),
            books={s: dict(ex=b.ex.to_state(), venue=b.venue.to_state(), gaps=b.gaps)
                   for s, b in self.books.items()})))

    def restore(self, prep: Prepared) -> bool:
        """Re-open today's session from the state file (same date). Returns True if restored."""
        st = read_json(self.state_path)
        if not st or st["date"] != str(prep.session.date.date()):
            return False
        self.equity = st["equity_open"]
        self.start_session(prep)
        self.risk.equity_open = st["equity_open"]
        self.risk.halted = st["halted"]
        for s, d in st["books"].items():
            self.books[s].ex.load_state(d["ex"])
            self.books[s].venue.load_state(d["venue"])
            self.books[s].gaps = d["gaps"]
        self.last_t, self.finished, self.closed = st["last_t"], st["finished"], st.get("closed", False)
        self.equity = st["equity"]
        self.save()      # start_session() above wrote a fresh state; put the restored one back at once
        self.log.write("restored", last_t=self.last_t, finished=self.finished)
        return True
