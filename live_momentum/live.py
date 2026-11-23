"""Phase 3 live trader: the PaperTrader driver with the real Binance venue.

Differences from paper:
  * orders go to Binance (LiveVenue). Construction requires cfg.sends_orders (mode live/testnet,
    dry_run=false, valid config, unexpired LIVE_MOMENTUM_ACK) and one-way position mode.
  * equity at the open = USDT wallet balance of the futures account.
  * size_mode="min": every entry uses the exchange minimum quantity (min notional + 5 %), and
    an entry the risk gate would shrink is blocked instead (a smaller order would be refused).
  * reconcile: at a fresh session start the account must hold no position and no open order
    in the traded symbols (otherwise the session does not start). After a restart, open orders
    that the saved state does not know are cancelled, the working order is refreshed, and the
    exchange position must equal the executor position; a mismatch flattens that symbol at
    market (reduce-only) and halts new entries for the day.
  * missed minutes are NOT replayed (orders cannot be placed in the past): decisions that were
    missed are skipped and logged; a pending entry past its deadline is dropped.
  * any order error the executor cannot absorb -> emergency flatten from the exchange's own
    positions, cancel all, halt for the day.
  * end of session: realised P&L and commissions from the exchange's trade history.
"""
from __future__ import annotations

import math
import time

import pandas as pd

from .bar_store import COLS
from .config import LiveConfig
from .history import Prepared
from .live_venue import LiveVenue, fmt
from .paper import PaperTrader, floor_step

MIN_SIZE_BUFFER = 1.05


class ReconcileError(RuntimeError):
    pass


def min_qty(info: dict, price: float) -> float:
    q = math.ceil(info["min_notional"] * MIN_SIZE_BUFFER / price / info["step"] - 1e-9) * info["step"]
    return max(q, info.get("min_qty", info["step"]))


def flatten_account(rest, symbols, exch, log=None, cid_prefix="lmK") -> dict:
    """Cancel all open orders and close every position in `symbols` at market, reduce-only.
    Uses only the exchange's own state (works without the trader's state)."""
    out, errors = {}, {}
    for s in symbols:                                   # every symbol is attempted, errors collected
        try:
            rest.cancel_all(s)
            amt = rest.positions([s])[s]
            if abs(amt) > 0:
                side = -1 if amt > 0 else 1
                cid = f"{cid_prefix}{time.time_ns() // 1_000_000 % 10**13:013d}{s[:3]}"
                step = max(exch[s].get("market_step", exch[s]["step"]), exch[s]["step"])
                r = rest.new_order(s, side, fmt(abs(amt), step, "round"), cid, reduce_only=True)
                out[s] = dict(amt=amt, status=r.get("status"), avg=r.get("avgPrice"))
        except Exception as e:                          # noqa: BLE001
            errors[s] = repr(e)[:300]
    if log is not None:
        log.write("flatten_account", orders=out, errors=errors)
    if errors:
        raise RuntimeError(f"flatten_account failed for {sorted(errors)}: {errors}")
    return out


class LiveTrader(PaperTrader):
    def __init__(self, cfg: LiveConfig, exch: dict, clock_ms, log, state_path, rest, equity: float,
                 history_days: int = 45):
        self.rest = rest
        super().__init__(cfg, exch, clock_ms, log, state_path, equity, history_days)
        if rest.position_mode_dual():
            raise ReconcileError("account is in hedge (dual-side) mode; one-way mode is required")
        self.emergency = False

    @staticmethod
    def _check_mode(cfg: LiveConfig) -> None:
        if cfg.mode not in ("live", "testnet") or not cfg.sends_orders:
            raise PermissionError("LiveTrader requires mode live/testnet, dry_run=false and a valid "
                                  "LIVE_MOMENTUM_ACK")

    def _make_venue(self, sym: str, start_ms: int):
        return LiveVenue(sym, self.rest, start_ms, self.clock_ms, self.exch[sym], self.log)

    def on_order_update(self, o: dict) -> None:
        b = self.books.get(o.get("s"))
        if b is not None:
            b.venue.on_order_update(o)

    # ------------------------------------------------------------------ sizing
    def _qty_fn(self, sym):
        base = super()._qty_fn(sym)

        def f(t, last):
            if self.cfg.size_mode != "min":
                return base(t, last)
            return min_qty(self.exch[sym], last)
        return f

    def _gate(self, sym):
        base = super()._gate(sym)

        def g(t, side, qty):
            if self.emergency:
                return 0.0
            q = base(t, side, qty)
            if self.cfg.size_mode == "min" and q + 1e-12 < qty:
                return 0.0               # a shrunk minimum order would be refused by the exchange
            return q
        return g

    # ------------------------------------------------------------------ reconcile
    def _prefix(self, sym):
        return self.books[sym].ex.cid_prefix

    def start_session(self, prep: Prepared, fresh: bool = True) -> None:
        if fresh:
            pos = self.rest.positions(self.cfg.symbols)
            opened = {s: self.rest.open_orders(s) for s in self.cfg.symbols}
            bad = {s: a for s, a in pos.items() if a} | {s: len(o) for s, o in opened.items() if o}
            if bad:
                raise ReconcileError(f"account not flat at the session start: {bad}. Close these "
                                     "positions/orders by hand (this trader only trades a flat account)")
        super().start_session(prep)

    def restore(self, prep: Prepared) -> bool:
        from .persistence import read_json
        st = read_json(self.state_path)
        if not st or st["date"] != str(prep.session.date.date()):
            return False
        # PaperTrader.restore calls start_session(prep): skip the flat-account check there
        orig = self.start_session
        self.start_session = lambda p: LiveTrader.start_session(self, p, fresh=False)
        try:
            ok = super().restore(prep)
        finally:
            self.start_session = orig
        if ok:
            self.reconcile()
        return ok

    def reconcile(self) -> None:
        pos = self.rest.positions(self.cfg.symbols)
        for sym, b in self.books.items():
            known = {o.cid for o in b.venue.orders.values()}
            for o in self.rest.open_orders(sym):
                if o["clientOrderId"] not in known:
                    self.rest.cancel_order(sym, o["clientOrderId"])
                    self.log.write("reconcile_cancel_unknown", sym=sym, cid=o["clientOrderId"])
            if b.ex.working is not None and b.ex.working.cid in b.venue.orders:
                b.venue.refresh(b.ex.working.cid)
            want = b.ex.pos * b.ex.qty
            pending_fill = b.ex.working is not None and b.venue.orders.get(b.ex.working.cid) is not None \
                and b.venue.orders[b.ex.working.cid].filled > 0
            if abs(pos[sym] - want) > 1e-9 and not pending_fill:
                self.log.write("reconcile_mismatch", sym=sym, exchange=pos[sym], state=want)
                self.risk.halt("reconcile_mismatch", sym=sym)
                b.ex.flatten(self.last_t, "reconcile")
                left = self.rest.positions([sym])[sym]
                if abs(left):
                    flatten_account(self.rest, [sym], self.exch, self.log)
        self.log.write("reconciled", positions=pos)
        self.save()

    # ------------------------------------------------------------------ boundary
    def on_boundary(self, now: pd.Timestamp, catchup_bars: dict | None = None) -> None:
        if self.prep is None or self.finished:
            return
        t = self.prep.session.minute(now)
        if t > self.last_t + 1:                              # late start / restart / outage: no replay
            self.log.write("skip_missed", from_t=self.last_t + 1, to_t=t - 1)
            for sym, b in self.books.items():
                p = b.ex.pending
                if p is not None and t >= p.deadline:
                    self.log.write("drop_pending", sym=sym, want=p.want, deadline=p.deadline)
                    b.ex.pending = None
            self.last_t = t - 1
        if catchup_bars:
            sess = self.prep.session
            for sym, df in catchup_bars.items():
                for ts, r in df.iterrows():
                    if sess.start <= ts < sess.end and sym in self.books:
                        self.books[sym].today.setdefault(ts, {c: r[c] for c in COLS})
        try:
            super().on_boundary(now, None)
        except Exception as e:                               # noqa: BLE001 - any order failure
            self.emergency_stop(t, e)

    def emergency_stop(self, t: int, err: BaseException) -> None:
        self.emergency = True
        self.log.write("emergency_stop", t=t, error=repr(err)[:500])
        self.risk.halt("order_error", error=repr(err)[:200])
        try:
            flatten_account(self.rest, self.cfg.symbols, self.exch, self.log)
        finally:
            for b in self.books.values():
                b.ex.working, b.ex.pending = None, None
                if b.ex.pos:
                    b.ex.pos, b.ex.qty, b.ex.entry = 0, 0.0, None
            self.last_t = t
            self.save()

    def _boundary(self, t, now, catchup: bool = False) -> None:
        super()._boundary(t, now, catchup)
        if self.risk.halted in ("kill_switch", "daily_loss") or self.risk.kill_requested():
            self.verify_flat(t)

    def verify_flat(self, t: int) -> None:
        """After a risk flatten the exchange must be flat too. A maker leg partially filled at the
        cancel leaves exposure the executor never booked: close it from the exchange's state."""
        pos = self.rest.positions(self.cfg.symbols)
        left = [s for s, b in self.books.items() if abs(pos[s] - b.ex.pos * b.ex.qty) > 1e-12]
        if left:
            self.log.write("risk_flatten_residual", t=t, positions={s: pos[s] for s in left})
            flatten_account(self.rest, left, self.exch, self.log)
            for s in left:
                self.books[s].venue.carry = None

    # ------------------------------------------------------------------ end of day
    def end_session(self, funding=None) -> dict:
        summary = super().end_session(funding)
        sess = self.prep.session
        a, z = int(sess.start.value // 1_000_000), int(sess.end.value // 1_000_000) + 5 * 60_000
        ex = {}
        for s in self.cfg.symbols:
            tr = self.rest.user_trades(s, a, z)
            ex[s] = dict(n=len(tr), realized=sum(float(x["realizedPnl"]) for x in tr),
                         commission=sum(float(x["commission"]) for x in tr if x.get("commissionAsset") == "USDT"),
                         maker=sum(1 for x in tr if x.get("maker")))
        bal = self.rest.balances().get("USDT", {})
        summary["exchange"] = dict(trades=ex, wallet_close=bal.get("balance"),
                                   realized=sum(v["realized"] for v in ex.values()),
                                   commission=sum(v["commission"] for v in ex.values()))
        self.log.write("exchange_close", **summary["exchange"])
        return summary
