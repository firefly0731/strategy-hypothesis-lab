"""Paper venue on the live trade tape and order book (Phase 1: no orders are sent).

Fill model, chosen to be the backtest rule evaluated on real trades:
  * post-only order: would be REJECTED (GTX) if it crosses the book at send time
    (buy limit >= best ask, sell limit <= best bid). A rejected order never fills; the
    executor's timeout then sends a market order, as maker_chase would after a re-post failure.
  * resting order fills when a trade prints THROUGH the limit after the send time
    (buy: price < limit, sell: price > limit). Touching the limit is not a fill.
  * market order fills at the best ask (buy) / bid (sell) at send time; if the book is
    missing or stale, at the last trade.

Per order it also records queue diagnostics: quantity traded AT the limit and THROUGH it
while resting, and the quantity at the best level at send time. The daily report uses them to
estimate how optimistic the trade-through rule is (a real order needs the queue ahead of it
to be consumed).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .executor import Fill

MS_PER_MIN = 60_000


@dataclass
class Book:
    bid: float = np.nan
    ask: float = np.nan
    bid_qty: float = np.nan
    ask_qty: float = np.nan
    ts: int = 0                 # exchange time (ms)
    last: float = np.nan        # last trade price
    last_ts: int = 0


@dataclass
class Resting:
    cid: str
    side: int
    qty: float
    limit: float
    t: int                      # session minute it was sent at
    send_ts: int                # ms
    rejected: bool = False
    at_qty: float = 0.0         # traded exactly at the limit while resting
    through_qty: float = 0.0    # traded through the limit while resting
    queue_ahead: float = np.nan  # best-level quantity on our side at send (if our price joins it)
    first_through_ts: int | None = None


@dataclass
class TapeVenue:
    session_start_ms: int
    clock_ms: callable                      # () -> current time in ms (wall clock, NTP-synced)
    book_stale_ms: int = 5_000
    book: Book = field(default_factory=Book)
    resting: dict = field(default_factory=dict)
    fills: list = field(default_factory=list)       # Fill awaiting poll
    history: list = field(default_factory=list)     # closed Resting records (diagnostics)
    events: list = field(default_factory=list)

    # ------------------------------------------------------------------ feed
    def on_book(self, bid, ask, bid_qty, ask_qty, ts):
        b = self.book
        b.bid, b.ask, b.bid_qty, b.ask_qty, b.ts = bid, ask, bid_qty, ask_qty, ts

    def on_trade(self, price: float, qty: float, ts: int):
        self.book.last, self.book.last_ts = price, ts
        for cid, r in list(self.resting.items()):
            if r.rejected or ts < r.send_ts:
                continue
            if price == r.limit:
                r.at_qty += qty
                continue
            through = (r.side > 0 and price < r.limit) or (r.side < 0 and price > r.limit)
            if not through:
                continue
            r.through_qty += qty
            if r.first_through_ts is None:
                r.first_through_ts = ts
                bar = int((ts - self.session_start_ms) // MS_PER_MIN)
                self.fills.append(Fill(cid, r.side, r.qty, r.limit, bar, True))
                self.history.append(r)
                del self.resting[cid]

    def on_bar_catchup(self, k: int, low: float, high: float):
        """Restart catch-up for a missed minute k: bar rule (same as the backtest)."""
        for cid, r in list(self.resting.items()):
            if r.rejected or k < r.t:
                continue
            if (r.side > 0 and low < r.limit) or (r.side < 0 and high > r.limit):
                self.fills.append(Fill(cid, r.side, r.qty, r.limit, k, True))
                r.first_through_ts = self.session_start_ms + k * MS_PER_MIN
                self.events.append(("catchup_fill", cid, k))
                self.history.append(r)
                del self.resting[cid]

    # ------------------------------------------------------------------ Venue protocol
    def post_only(self, cid, side, qty, limit, t, reduce_only):
        now = self.clock_ms()
        b = self.book
        r = Resting(cid, side, qty, limit, t, now)
        fresh = now - b.ts <= self.book_stale_ms and np.isfinite(b.bid) and np.isfinite(b.ask)
        if fresh:
            r.rejected = bool((side > 0 and limit >= b.ask) or (side < 0 and limit <= b.bid))
            same = b.bid if side > 0 else b.ask
            r.queue_ahead = (b.bid_qty if side > 0 else b.ask_qty) if limit == same else 0.0
        if r.rejected:
            self.events.append(("post_only_reject", cid, side, limit, b.bid, b.ask))
        self.resting[cid] = r

    def cancel(self, cid, t):
        r = self.resting.pop(cid, None)
        if r is not None:
            self.history.append(r)

    def poll(self, t):
        """Fills on bars < t (the executor sees a fill at the next minute boundary)."""
        out = [f for f in self.fills if f.bar < t]
        self.fills = [f for f in self.fills if f.bar >= t]
        return out

    def market(self, cid, side, qty, t, reduce_only):
        now = self.clock_ms()
        b = self.book
        fresh = now - b.ts <= self.book_stale_ms
        px = (b.ask if side > 0 else b.bid) if fresh else np.nan
        src = "book"
        if not np.isfinite(px):
            px, src = b.last, "last"
        self.events.append(("market", cid, side, qty, px, src, b.bid, b.ask))
        return Fill(cid, side, qty, float(px), t, False)

    # ------------------------------------------------------------------ persistence
    def to_state(self) -> dict:
        from dataclasses import asdict
        from .executor import _jsonable
        return _jsonable({"resting": [asdict(r) for r in self.resting.values()],
                          "fills": [asdict(f) for f in self.fills],
                          "history": [asdict(r) for r in self.history]})

    def load_state(self, d: dict) -> None:
        def res(x):
            x = dict(x)
            x["queue_ahead"] = np.nan if x.get("queue_ahead") is None else x["queue_ahead"]
            return Resting(**x)
        self.resting = {x["cid"]: res(x) for x in d["resting"]}
        self.fills = [Fill(**f) for f in d["fills"]]
        self.history = [res(x) for x in d["history"]]
