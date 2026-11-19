"""Event-driven backtest on 1-minute bars with maker/taker execution models.

Timeline at decision minute m (see signals.py):
  * signal uses bars 0..m-1 (closed), price = close of bar m-1
  * orders are sent at time start+m; earliest bar that can fill is bar m
  * a taker order fills at open of bar m (+ slippage)
  * a maker (post-only) order is priced off the last known trade
    (close of bar m-1) and can fill on bars m, m+1, ... only if the market
    trades *through* the limit (buy: low < limit; sell: high > limit).
    Merely touching the limit is treated as NOT filled (queue position).

Exit rules follow the paper: at each decision time a long is closed when
price < max(UB, VWAP), a short when price > min(LB, VWAP); an opposite band
break flips the position. Everything is flat at the session end.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from .sessions import SessionMatrix
from .signals import Signals


@dataclass
class Config:
    # execution
    entry_mode: str = "taker"          # taker | maker
    entry_fallback: str = "skip"       # maker entry unfilled at timeout: skip | taker
    exit_mode: str = "taker"           # taker | maker (unfilled -> taker at timeout)
    maker_timeout: int = 5             # minutes a maker order rests
    maker_offset_ticks: float = 1.0    # buy at last - k*tick, sell at last + k*tick
    eod_maker_window: int = 10         # maker EOD exit starts this many minutes before end
    tick: float = 0.1
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    taker_slippage_bps: float = 1.0
    include_funding: bool = True
    # sizing
    sizing: str = "vol"                # vol | fixed
    target_vol: float = 0.02           # daily vol target (paper: 2%)
    max_leverage: float = 4.0
    fixed_leverage: float = 1.0
    initial_equity: float = 100_000.0

    def to_dict(self):
        return asdict(self)


@dataclass
class Result:
    trades: pd.DataFrame
    sessions: pd.DataFrame
    missed: pd.DataFrame
    config: Config = field(default_factory=Config)


class _Fill:
    __slots__ = ("bar", "price", "maker")

    def __init__(self, bar, price, maker):
        self.bar, self.price, self.maker = bar, price, maker


def _taker_price(m: SessionMatrix, i: int, t: int, side: int, slip: float) -> float:
    n = m.C.shape[1]
    base = m.O[i, t] if t < n else m.C[i, n - 1]
    return base * (1.0 + side * slip)


def _order(m: SessionMatrix, i: int, t: int, side: int, mode: str, deadline: int,
           cfg: Config, fallback_taker: bool, timeout: int | None = None) -> _Fill | None:
    """Send an order at bar t for `side` (+1 buy / -1 sell). deadline = first bar
    at which a resting maker order is cancelled (taker fallback executes there)."""
    slip = cfg.taker_slippage_bps * 1e-4
    if mode == "taker":
        return _Fill(t, _taker_price(m, i, t, side, slip), False)
    last = m.C[i, t - 1]                               # last trade known at send time
    limit = last - side * cfg.maker_offset_ticks * cfg.tick
    end = min(t + (cfg.maker_timeout if timeout is None else timeout), deadline)
    if end > t:
        if side > 0:
            hit = np.flatnonzero(m.L[i, t:end] < limit)
        else:
            hit = np.flatnonzero(m.H[i, t:end] > limit)
        if hit.size:
            return _Fill(t + int(hit[0]), limit, True)
    if fallback_taker:
        return _Fill(end, _taker_price(m, i, end, side, slip), False)
    return None


def _funding_cost(m, i, side, qty, t_in, t_out, f_times, f_rates) -> float:
    """Funding paid while holding through settlement times f with
    bar_time(t_in) < f <= bar_time(t_out). Positive rate: long pays."""
    if f_times is None:
        return 0.0
    a = m.bar_time(i, t_in).value
    b = m.bar_time(i, t_out).value
    lo = np.searchsorted(f_times, a, side="right")
    hi = np.searchsorted(f_times, b, side="right")
    cost = 0.0
    for k in range(lo, hi):
        kbar = int((f_times[k] - m.start_utc[i].value) // 60_000_000_000)
        price = m.C[i, max(kbar - 1, 0)]
        cost += side * qty * price * f_rates[k]
    return cost


def run_backtest(m: SessionMatrix, s: Signals, cfg: Config,
                 funding: pd.DataFrame | None = None) -> Result:
    n_min = m.C.shape[1]
    dm = s.dec_min
    eod_start = n_min - cfg.eod_maker_window if cfg.exit_mode == "maker" else n_min
    f_times = f_rates = None
    if cfg.include_funding and funding is not None and len(funding):
        f_times = pd.DatetimeIndex(funding["time"]).as_unit("ns").asi8
        f_rates = funding["rate"].to_numpy()

    equity = cfg.initial_equity
    trades, sess_rows, missed = [], [], []

    for i in range(m.n):
        eq0 = equity
        ready = m.tradable[i] and np.isfinite(s.sigma[i]).all() and np.isfinite(s.prev_close[i])
        if cfg.sizing == "vol":
            ready = ready and np.isfinite(s.daily_vol[i]) and s.daily_vol[i] > 0
        if not ready:
            sess_rows.append((m.dates[i], eq0, equity, 0, False))
            continue
        lev = (min(cfg.max_leverage, cfg.target_vol / s.daily_vol[i])
               if cfg.sizing == "vol" else cfg.fixed_leverage)
        qty = eq0 * lev / s.sess_open[i]

        pos, entry = 0, None
        n_tr = 0

        def close_pos(fill: _Fill, reason: str):
            nonlocal pos, entry, equity, n_tr
            side, e = pos, entry
            fee_rate_in = cfg.maker_fee if e.maker else cfg.taker_fee
            fee_rate_out = cfg.maker_fee if fill.maker else cfg.taker_fee
            fees = qty * (e.price * fee_rate_in + fill.price * fee_rate_out)
            fund = _funding_cost(m, i, side, qty, e.bar, fill.bar, f_times, f_rates)
            gross = side * qty * (fill.price - e.price)
            pnl = gross - fees - fund
            equity += pnl
            trades.append(dict(
                date=m.dates[i], side=side,
                entry_time=m.bar_time(i, e.bar), exit_time=m.bar_time(i, min(fill.bar, n_min - 1)),
                entry_px=e.price, exit_px=fill.price, qty=qty, notional=qty * e.price,
                leverage=lev, entry_maker=e.maker, exit_maker=fill.maker, exit_reason=reason,
                gross=gross, fees=fees, funding=fund, pnl=pnl,
                ret_notional=pnl / (qty * e.price), ret_equity=pnl / eq0,
                hold_min=fill.bar - e.bar,
            ))
            pos, entry = 0, None
            n_tr += 1

        for j, t in enumerate(dm):
            nxt = dm[j + 1] if j + 1 < len(dm) else n_min
            deadline = min(nxt, eod_start)
            p, ub, lb, vw = s.px[i, j], s.ub[i, j], s.lb[i, j], s.vwap[i, j]

            if pos == 0:
                want = 1 if p > ub else (-1 if p < lb else 0)
            elif pos == 1:
                want = 1 if p >= max(ub, vw) else (-1 if p < lb else 0)
            else:
                want = -1 if p <= min(lb, vw) else (1 if p > ub else 0)
            if want == pos:
                continue

            tt = t
            if pos != 0:
                f = _order(m, i, tt, -pos, cfg.exit_mode, deadline, cfg, fallback_taker=True)
                close_pos(f, "flip" if want else "stop")
                tt = f.bar + (1 if f.maker else 0)
            if want != 0 and tt < deadline:
                f = _order(m, i, tt, want, cfg.entry_mode, deadline, cfg,
                           fallback_taker=(cfg.entry_fallback == "taker"))
                if f is None:
                    missed.append(dict(date=m.dates[i], time=m.bar_time(i, t), side=want,
                                       px=p, sess_close=m.C[i, -1],
                                       move_to_close=want * (m.C[i, -1] / p - 1.0)))
                elif f.bar < n_min:
                    pos, entry = want, f

        if pos != 0:
            if cfg.exit_mode == "maker":
                t_eod = max(eod_start, entry.bar + 1)
                f = _order(m, i, t_eod, -pos, "maker", n_min, cfg, fallback_taker=True,
                           timeout=n_min - t_eod)
            else:
                f = _Fill(n_min, _taker_price(m, i, n_min, -pos, cfg.taker_slippage_bps * 1e-4), False)
            close_pos(f, "eod")

        sess_rows.append((m.dates[i], eq0, equity, n_tr, True))

    sessions = pd.DataFrame(sess_rows, columns=["date", "equity_start", "equity_end", "n_trades", "active"])
    sessions["ret"] = sessions["equity_end"] / sessions["equity_start"] - 1.0
    return Result(pd.DataFrame(trades), sessions, pd.DataFrame(missed), cfg)
