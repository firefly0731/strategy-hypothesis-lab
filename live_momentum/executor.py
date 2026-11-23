"""maker_chase execution as an event-driven state machine.

The executor is driven once per minute boundary: `step(t, last, want_fn)` runs at time
session_start + t, when bars 0..t-1 are closed. It reproduces run_backtest's order logic:

  decision at t      exit (if any): post-only at last -/+ k ticks, rests until
                     min(t + timeout, deadline), deadline = min(next decision, EOD start);
                     unfilled -> market at the timeout minute.
                     entry (if any) is sent after the exit has filled: at the timeout
                     minute for a market exit, at the minute after the fill bar for a
                     maker exit, and only if that is before the deadline.
  entry              post-only at last -/+ k ticks; unfilled at the timeout -> market.
  EOD                from EOD start (15:50) post-only exit; at the session end -> market.

`last` is the last trade known at the send time (close of bar t-1). A maker order sent at
t can fill on bars t, t+1, ... and only if the market trades THROUGH the limit; the fill is
seen at the next minute boundary. Market orders fill immediately at the venue's price.

The venue is pluggable: SimBarVenue replays 1m bars (backtest fill rules); a paper venue
on the live order book and the Binance venue come in later phases.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol

import numpy as np

from crypto_intraday_momentum.backtest import Config


@dataclass(frozen=True)
class Fill:
    cid: str
    side: int          # +1 buy / -1 sell
    qty: float
    price: float
    bar: int           # session bar index of the fill
    maker: bool


class Venue(Protocol):
    def post_only(self, cid: str, side: int, qty: float, limit: float, t: int, reduce_only: bool) -> None: ...
    def market(self, cid: str, side: int, qty: float, t: int, reduce_only: bool) -> Fill: ...
    def cancel(self, cid: str, t: int) -> None: ...
    def poll(self, t: int) -> list[Fill]: ...


@dataclass
class _Order:
    cid: str
    kind: str          # entry | exit
    side: int
    qty: float
    limit: float
    sent: int
    end: int           # minute at which it is cancelled (-> market)
    reason: str | None = None          # exit reason: stop | flip | eod
    follow: tuple | None = None        # (want, dec_j, deadline) entry after this exit
    dec_j: int | None = None           # decision index of an entry


@dataclass
class _Pending:
    at: int            # minute the entry may be sent (backtest's tt)
    want: int
    dec_j: int
    deadline: int


@dataclass
class TradeRecord:
    side: int
    qty: float
    entry_bar: int
    exit_bar: int
    entry_px: float
    exit_px: float
    entry_maker: bool
    exit_maker: bool
    exit_reason: str
    dec_j: int
    entry_kind: str


@dataclass
class MakerChaseExecutor:
    venue: Venue
    cfg: Config
    dec_min: np.ndarray
    n_min: int
    qty_fn: Callable[[int, float], float]      # (t, last) -> order quantity for a new entry
    cid_prefix: str = "lm"
    # risk gate for NEW entries: (t, side, qty) -> approved qty (<= 0 blocks the entry).
    # Exits are never gated: they only reduce risk.
    gate: Callable[[int, int, float], float] | None = None
    listener: Callable[[tuple], None] | None = None   # receives every log event
    pos: int = 0
    qty: float = 0.0
    entry: Fill | None = None
    entry_j: int | None = None
    entry_kind: str | None = None
    last_exit: str | None = None
    working: _Order | None = None
    pending: _Pending | None = None
    trades: list[TradeRecord] = field(default_factory=list)
    log: list[tuple] = field(default_factory=list)
    _seq: int = 0

    def __post_init__(self):
        if self.cfg.entry_mode != "maker" or self.cfg.exit_mode != "maker" or self.cfg.entry_fallback != "taker":
            raise ValueError("MakerChaseExecutor implements maker_chase only")
        if self.cfg.post_close_min is not None:
            raise ValueError("post-close holding is not part of the adopted configuration")
        self.eod_start = self.n_min - self.cfg.eod_maker_window
        if len(self.dec_min) and self.eod_start <= int(self.dec_min[-1]):
            raise ValueError("EOD maker window must start after the last decision")

    # ------------------------------------------------------------------ helpers
    def _cid(self, tag: str) -> str:
        self._seq += 1
        return f"{self.cid_prefix}{tag}{self._seq:03d}"

    def _limit(self, last: float, side: int) -> float:
        c = self.cfg
        if c.maker_offset_bps is not None:
            return last * (1.0 - side * c.maker_offset_bps * 1e-4)
        return last - side * c.maker_offset_ticks * c.tick

    def _deadline(self, j: int) -> int:
        nxt = int(self.dec_min[j + 1]) if j + 1 < len(self.dec_min) else self.n_min
        return min(nxt, self.eod_start)

    def _emit(self, ev: tuple) -> None:
        self.log.append(ev)
        if self.listener is not None:
            self.listener(ev)

    def _send(self, t: int, last: float, kind: str, side: int, qty: float, end: int, **kw) -> None:
        o = _Order(self._cid(kind[0]), kind, side, qty, self._limit(last, side), t, end, **kw)
        self.venue.post_only(o.cid, side, qty, o.limit, t, reduce_only=(kind == "exit"))
        self.working = o
        self._emit((t, "post", kind, side, o.limit, o.cid))

    def _send_entry(self, t: int, last: float, side: int, end: int, dec_j: int) -> None:
        qty = self.qty_fn(t, last)
        if self.gate is not None:
            qty = self.gate(t, side, qty)
        if not qty or qty <= 0:
            self._emit((t, "blocked", "entry", side, last, None))
            return
        self._send(t, last, "entry", side, qty, end, dec_j=dec_j)

    def _filled(self, o: _Order, f: Fill) -> None:
        self.working = None
        self._emit((f.bar, "fill", o.kind, f.side, f.price, "maker" if f.maker else "taker"))
        if o.kind == "entry":
            self.pos, self.qty, self.entry, self.entry_j = o.side, f.qty, f, o.dec_j
            self.entry_kind = ("first" if self.last_exit is None else
                               "flip" if self.last_exit == "flip" else "reentry")
            return
        e = self.entry
        self.trades.append(TradeRecord(self.pos, self.qty, e.bar, f.bar, e.price, f.price, e.maker,
                                       f.maker, o.reason, self.entry_j, self.entry_kind))
        self.last_exit = o.reason
        self.pos, self.qty, self.entry = 0, 0.0, None
        if o.follow is not None:
            want, j, deadline = o.follow
            self.pending = _Pending(f.bar + (1 if f.maker else 0), want, j, deadline)

    # ------------------------------------------------------------------ driver
    def step(self, t: int, last: float, want_fn: Callable[[int], int] | None = None) -> None:
        """Run at minute boundary t (bars < t closed). want_fn(pos) -> wanted position,
        given only at decision minutes of a ready session."""
        # 1) maker fills on bars < t
        if self.working is not None:
            for f in self.venue.poll(t):
                if self.working is not None and f.cid == self.working.cid:
                    self._filled(self.working, f)
        # 2) timeout -> cancel + market
        o = self.working
        if o is not None and t >= o.end:
            self.venue.cancel(o.cid, t)
            self._emit((t, "cancel", o.kind, o.side, o.limit, o.cid))
            f = self.venue.market(self._cid("m"), o.side, o.qty, t, reduce_only=(o.kind == "exit"))
            if o.kind == "entry" and not f.qty > 0:          # real venue refused the entry
                self.working = None
                self._emit((t, "blocked", "entry", o.side, f.price, "venue_refused"))
            else:
                self._filled(o, f)
        # 3) entry waiting for its exit
        p = self.pending
        if p is not None and p.at <= t:
            self.pending = None
            if p.at < p.deadline:
                end = min(p.at + self.cfg.maker_timeout, p.deadline)
                self._send_entry(t, last, p.want, end, p.dec_j)
        # 4) decision
        k = np.flatnonzero(self.dec_min == t)
        if want_fn is not None and k.size:
            j = int(k[0])
            if self.working is not None or self.pending is not None:
                raise RuntimeError(f"order still working at decision minute {t}")
            want = want_fn(self.pos)
            if want != self.pos:
                deadline = self._deadline(j)
                end = min(t + self.cfg.maker_timeout, deadline)
                if self.pos != 0:
                    self._send(t, last, "exit", -self.pos, self.qty, end,
                               reason="flip" if want else "stop",
                               follow=(want, j, deadline) if want else None)
                elif t < deadline:
                    self._send_entry(t, last, want, end, j)
        # 5) end of day
        if self.pos != 0 and self.working is None:
            t_eod = max(self.eod_start, self.entry.bar + 1)
            if t >= t_eod and t < self.n_min:
                self._send(t, last, "exit", -self.pos, self.qty, self.n_min, reason="eod")
            elif t >= self.n_min:
                o = _Order(self._cid("m"), "exit", -self.pos, self.qty, np.nan, t, t, reason="eod")
                self._filled(o, self.venue.market(o.cid, o.side, o.qty, t, reduce_only=True))

    # ------------------------------------------------------------------ risk actions
    def flatten(self, t: int, reason: str) -> None:
        """Cancel everything and close the position at market now (risk limit / kill switch)."""
        o = self.working
        if o is not None:
            self.venue.cancel(o.cid, t)
            self._emit((t, "cancel", o.kind, o.side, o.limit, o.cid))
            self.working = None
        if self.pending is not None:
            self._emit((t, "drop_pending", "entry", self.pending.want, None, None))
            self.pending = None
        if self.pos != 0:
            x = _Order(self._cid("k"), "exit", -self.pos, self.qty, np.nan, t, t, reason=reason)
            self._filled(x, self.venue.market(x.cid, x.side, x.qty, t, reduce_only=True))

    # ------------------------------------------------------------------ persistence
    _STATE = ("pos", "qty", "entry_j", "entry_kind", "last_exit", "_seq")

    def to_state(self) -> dict:
        d = {k: getattr(self, k) for k in self._STATE}
        d["entry"] = asdict(self.entry) if self.entry else None
        d["working"] = asdict(self.working) if self.working else None
        d["pending"] = asdict(self.pending) if self.pending else None
        d["trades"] = [asdict(r) for r in self.trades]
        return _jsonable(d)

    def load_state(self, d: dict) -> None:
        for k in self._STATE:
            setattr(self, k, d[k])
        self.entry = Fill(**d["entry"]) if d["entry"] else None
        w = d["working"]
        if w:
            w = dict(w)
            if w.get("follow") is not None:
                w["follow"] = tuple(w["follow"])
            self.working = _Order(**w)
        else:
            self.working = None
        self.pending = _Pending(**d["pending"]) if d["pending"] else None
        self.trades = [TradeRecord(**r) for r in d["trades"]]


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


class SimBarVenue:
    """Fills from 1m bars with the backtest's rules (trade-through for makers,
    next-bar open + slippage for market orders, last close for the session end)."""

    def __init__(self, O, H, L, C, slippage_bps: float):
        self.O, self.H, self.L, self.C = O, H, L, C
        self.slip = slippage_bps * 1e-4
        self.resting: dict[str, tuple] = {}

    def post_only(self, cid, side, qty, limit, t, reduce_only):
        self.resting[cid] = (side, qty, limit, t)

    def cancel(self, cid, t):
        self.resting.pop(cid, None)

    def poll(self, t):
        k = t - 1                                         # bar that just closed
        out = []
        for cid, (side, qty, limit, sent) in list(self.resting.items()):
            if k < sent:
                continue
            if (side > 0 and self.L[k] < limit) or (side < 0 and self.H[k] > limit):
                out.append(Fill(cid, side, qty, limit, k, True))
                del self.resting[cid]
        return out

    def market(self, cid, side, qty, t, reduce_only):
        n = len(self.C)
        base = self.O[t] if t < n else self.C[n - 1]
        return Fill(cid, side, qty, base * (1.0 + side * self.slip), t, False)
