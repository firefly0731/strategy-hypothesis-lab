"""Real Binance venue for MakerChaseExecutor (one instance per symbol).

Same contract as SimBarVenue / TapeVenue:
  post_only   LIMIT GTX (post-only), newClientOrderId = executor cid, reduceOnly for exits
  poll(t)     fills on bars < t. Order state comes from the user data stream (on_order_update)
              and is confirmed by a REST query of every open order at each boundary
  cancel      by client id. A partial (or complete) fill found at the cancel is carried into
              the following market order, so the executor sees one fill for the full leg
  market      MARKET with newOrderRespType=RESULT for the remaining quantity only

Edge cases:
  * GTX that would cross (-5022 or status EXPIRED): the order is marked rejected and never
    fills. The executor sends a market order at its timeout, as with TapeVenue.
  * entry remainder below the exchange minimum notional after a partial maker fill: the leg
    is closed at the partial quantity (Fill.qty < asked). Reduce-only exits are exempt.
  * an entry market order the exchange refuses (margin, min notional): a zero-quantity fill
    tells the executor the entry did not happen. A refused EXIT raises VenueError: the trader
    then flattens from the exchange's own positions and halts.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from decimal import Decimal

from .binance_signed import POST_ONLY_REJECT, BinanceError
from .executor import Fill

TERMINAL = ("FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED")


class VenueError(RuntimeError):
    pass


def fmt(x: float, inc: float, mode: str = "round") -> str:
    """x on the `inc` grid as an exact decimal string (no float artefacts)."""
    q = x / inc
    n = math.floor(q + 1e-9) if mode == "floor" else math.ceil(q - 1e-9) if mode == "ceil" else round(q)
    d = Decimal(str(inc))
    return str((d * n).quantize(d))


@dataclass
class LiveOrder:
    cid: str
    side: int
    qty: float
    limit: float | None
    sent_t: int
    reduce_only: bool
    status: str = "NEW"
    filled: float = 0.0
    avg: float = 0.0
    update_ms: int = 0
    emitted: bool = False
    error: str | None = None


class LiveVenue:
    def __init__(self, sym: str, rest, session_start_ms: int, clock_ms, info: dict, log=None):
        self.sym, self.rest, self.start_ms, self.clock_ms = sym, rest, session_start_ms, clock_ms
        self.tick, self.step = info["tick"], info["step"]
        self.market_step = max(info.get("market_step", self.step), self.step)
        self.min_notional = info["min_notional"]
        self.log = log
        self.orders: dict[str, LiveOrder] = {}
        self.carry: tuple[float, float] | None = None     # (qty, avg) maker fill found at a cancel
        self.events: list[tuple] = []
        self.errors = 0

    # market data hooks used by TapeVenue; the real venue needs none of them
    def on_trade(self, *a): pass
    def on_book(self, *a): pass
    def on_bar_catchup(self, *a): pass

    @property
    def history(self):
        return list(self.orders.values())

    def _ev(self, *ev):
        self.events.append(ev)
        if self.log is not None:
            self.log.write("venue", sym=self.sym, ev=list(ev))

    def _bar(self, ms: int) -> int:
        return int((ms - self.start_ms) // 60_000)

    # ------------------------------------------------------------------ order state
    def _apply(self, o: LiveOrder, d: dict) -> None:
        """REST order dict or ORDER_TRADE_UPDATE 'o' payload."""
        status = d.get("status", d.get("X"))
        filled = float(d.get("executedQty", d.get("z", o.filled)) or 0.0)
        avg = float(d.get("avgPrice", d.get("ap", 0.0)) or 0.0)
        ts = int(d.get("updateTime", d.get("T", 0)) or 0)
        if filled + 1e-12 < o.filled:            # stale message (out of order): ignore
            return
        o.status = status or o.status
        o.filled, o.avg = filled, (avg if avg > 0 else o.avg)
        o.update_ms = max(o.update_ms, ts)

    def on_order_update(self, d: dict) -> None:
        o = self.orders.get(d.get("c"))
        if o is not None:
            self._apply(o, d)
            self._ev("ws", o.cid, o.status, o.filled, o.avg, d.get("n"), d.get("N"), d.get("m"))

    def refresh(self, cid: str) -> LiveOrder:
        o = self.orders[cid]
        if o.status not in TERMINAL:
            self._apply(o, self.rest.query_order(self.sym, cid))
        return o

    # ------------------------------------------------------------------ Venue protocol
    def post_only(self, cid, side, qty, limit, t, reduce_only):
        px = fmt(limit, self.tick, "floor" if side > 0 else "ceil")    # never more aggressive
        o = LiveOrder(cid, side, qty, float(px), t, reduce_only)
        self.orders[cid] = o
        try:
            r = self.rest.new_order(self.sym, side, fmt(qty, self.step, "floor"), cid, limit=px,
                                    post_only=True, reduce_only=reduce_only)
            self._apply(o, r)
        except BinanceError as e:
            o.status, o.error = "REJECTED", f"{e.code}: {e.msg}"
            if e.code != POST_ONLY_REJECT:
                self.errors += 1
        self._ev("post", cid, side, qty, px, reduce_only, o.status, o.error)

    def poll(self, t):
        out = []
        for o in self.orders.values():
            if o.emitted or o.limit is None:
                continue
            if o.status not in TERMINAL:
                self.refresh(o.cid)
            if o.status == "FILLED" and self._bar(o.update_ms) < t:
                o.emitted = True
                out.append(Fill(o.cid, o.side, o.filled, o.avg or o.limit, max(self._bar(o.update_ms), o.sent_t),
                                True))
        return out

    def cancel(self, cid, t):
        o = self.orders.get(cid)
        if o is None or o.emitted:
            return
        if o.status not in TERMINAL:
            r = self.rest.cancel_order(self.sym, cid)
            if r is not None:
                self._apply(o, r)
            if o.status not in TERMINAL:          # cancel acknowledged before the final state
                self.refresh(cid)
        o.emitted = True                          # never reported by poll after a cancel
        if o.filled > 0:
            self.carry = (o.filled, o.avg or o.limit)
        self._ev("cancel", cid, o.status, o.filled, o.avg)

    def market(self, cid, side, qty, t, reduce_only):
        cq, cavg = self.carry or (0.0, 0.0)
        self.carry = None
        rest_qty = float(fmt(qty - cq, self.market_step, "floor"))
        if rest_qty <= 0:                                           # the maker leg filled after all
            self._ev("market_skip", cid, side, qty, cq)
            return Fill(cid, side, cq, cavg, t, True)
        if not reduce_only and cq > 0:
            if rest_qty * cavg < self.min_notional:                  # remainder too small to send
                self._ev("market_skip_small", cid, side, rest_qty, cq)
                return Fill(cid, side, cq, cavg, t, True)
        o = LiveOrder(cid, side, rest_qty, None, t, reduce_only)
        self.orders[cid] = o
        try:
            r = self.rest.new_order(self.sym, side, fmt(rest_qty, self.market_step, "floor"), cid,
                                    reduce_only=reduce_only)
            self._apply(o, r)
            for _ in range(10):
                if o.status in TERMINAL:
                    break
                time.sleep(0.3)
                self.refresh(cid)
        except BinanceError as e:
            o.status, o.error = "REJECTED", f"{e.code}: {e.msg}"
        o.emitted = True
        self._ev("market", cid, side, rest_qty, o.status, o.filled, o.avg, o.error)
        if o.status != "FILLED" or o.filled <= 0:
            self.errors += 1
            if reduce_only:
                raise VenueError(f"{self.sym} exit market order {cid} not filled: {o.status} {o.error}")
            if cq > 0:
                return Fill(cid, side, cq, cavg, t, True)
            return Fill(cid, side, 0.0, float("nan"), t, False)     # entry did not happen
        tot = cq + o.filled
        return Fill(cid, side, tot, (cq * cavg + o.filled * o.avg) / tot, t, cq >= o.filled)

    # ------------------------------------------------------------------ persistence
    def to_state(self) -> dict:
        return {"orders": [asdict(o) for o in self.orders.values()], "carry": self.carry, "errors": self.errors}

    def load_state(self, d: dict) -> None:
        self.orders = {x["cid"]: LiveOrder(**x) for x in d.get("orders", [])}
        self.carry = tuple(d["carry"]) if d.get("carry") else None
        self.errors = d.get("errors", 0)
