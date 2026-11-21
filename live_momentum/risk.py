"""Risk limits. They only restrict the strategy: they can block or shrink NEW entries and
force a flatten; they never open or enlarge positions.

  * kill switch      file exists (or `cli kill`) -> cancel all + flatten + no new entries
                     until the file is removed
  * daily max loss   realised + unrealised P&L of today <= -limit * equity at the open
                     -> flatten + no new entries for the rest of the session
  * per-symbol cap   new entry notional clipped to max_notional_per_symbol
  * gross leverage   sum |open notional| + new notional <= max_gross_leverage * equity
                     (the entry is clipped to the remaining room)
  * stale data       a symbol whose market data is older than stale_data_sec gets no new
                     entries; exits still go out (they reduce risk)
  * clock            |local - exchange time| > max_clock_offset_ms -> no new entries
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import RiskLimits


@dataclass
class RiskManager:
    limits: RiskLimits
    equity_open: float
    max_clock_offset_ms: float = 1_000.0
    halted: str | None = None              # reason new entries are stopped for the session
    clock_offset_ms: float = 0.0
    events: list = field(default_factory=list)

    # ---------------------------------------------------------------- kill switch
    def kill_requested(self) -> bool:
        return Path(self.limits.kill_switch_file).exists()

    # ---------------------------------------------------------------- loss limit
    def check_loss(self, pnl_today: float) -> bool:
        """True if the daily loss limit is breached now (caller flattens)."""
        breached = pnl_today <= -self.limits.daily_max_loss_pct * self.equity_open
        if breached and self.halted is None:
            self.halt("daily_loss", pnl=pnl_today)
        return breached

    def halt(self, reason: str, **info) -> None:
        if self.halted is None:
            self.halted = reason
            self.events.append(("halt", reason, info))

    # ---------------------------------------------------------------- entry gate
    def approve_entry(self, sym: str, side: int, qty: float, price: float,
                      open_notional: dict, data_age_sec: float) -> tuple[float, str | None]:
        """Approved quantity (may be 0) and the reason for any reduction."""
        lim = self.limits
        if self.kill_requested():
            return 0.0, "kill_switch"
        if self.halted:
            return 0.0, self.halted
        if data_age_sec > lim.stale_data_sec:
            return 0.0, "stale_data"
        if abs(self.clock_offset_ms) > self.max_clock_offset_ms:
            return 0.0, "clock_offset"
        if qty <= 0 or not price > 0:
            return 0.0, "bad_qty"
        notional = qty * price
        reason = None
        if lim.max_notional_per_symbol > 0 and notional > lim.max_notional_per_symbol:
            notional, reason = lim.max_notional_per_symbol, "symbol_cap"
        room = lim.max_gross_leverage * self.equity_open - sum(
            abs(v) for k, v in open_notional.items() if k != sym)
        if notional > room:
            notional, reason = max(room, 0.0), "gross_leverage"
        return notional / price, reason
