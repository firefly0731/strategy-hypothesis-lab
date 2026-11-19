"""Trade simulator for fade / mean-reversion orders on session matrices.

A strategy produces an `Orders` object: for every session i and decision j
    side[i, j]    +1 buy / -1 sell / 0 nothing      (decided from bars < dec_min[j])
    target[i, j]  take-profit price (NaN = none)
    stop[i, j]    close-based stop price (NaN = none)
    tstop[i, j]   bar index at whose OPEN the position is closed (<= n_minutes)

Fill conventions copy `crypto_intraday_momentum/backtest.py`:
  * taker: open of bar t (+- slippage), taker fee.
  * maker: post-only limit priced off the last known close; fills only if the
    market trades THROUGH it (buy: low < limit, sell: high > limit); maker fee.
  * a maker entry filled during bar b can only be exited from bar b + 1
    (we do not know where inside bar b the fill happened). A taker entry at the
    open of bar b can be exited from bar b on.
  * close-based conditions (stop, taker target) seen at the close of bar k are
    executed at the open of bar k + 1.
  * funding is charged for every settlement crossed (positive rate: long pays).
One position per symbol at a time; decisions while a position is open are ignored.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_intraday_momentum.backtest import _funding_cost
from crypto_intraday_momentum.sessions import SessionMatrix


@dataclass(frozen=True)
class Exec:
    mode: str = "maker"            # taker | maker
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    slip_bps: float = 1.0
    maker_offset_bps: float = 0.5
    entry_timeout: int = 5         # minutes a maker entry rests (then skipped)
    exit_window: int = 5           # maker time-stop exit is posted this many bars before tstop
    include_funding: bool = True


@dataclass
class Orders:
    dec_min: np.ndarray            # (n_dec,)
    side: np.ndarray               # (n, n_dec) int
    target: np.ndarray             # (n, n_dec)
    stop: np.ndarray               # (n, n_dec)
    tstop: np.ndarray              # (n, n_dec) int


def _first(mask: np.ndarray) -> int:
    h = np.flatnonzero(mask)
    return int(h[0]) if h.size else -1


def simulate(m: SessionMatrix, o: Orders, ex: Exec, funding: pd.DataFrame | None = None,
             symbol: str = "") -> pd.DataFrame:
    """Returns one row per trade (unit notional: returns are fractions of entry notional)."""
    n_min = m.C.shape[1]
    slip = ex.slip_bps * 1e-4
    off = ex.maker_offset_bps * 1e-4
    f_times = f_rates = None
    if ex.include_funding and funding is not None and len(funding):
        f_times = pd.DatetimeIndex(funding["time"]).as_unit("ns").asi8
        f_rates = funding["rate"].to_numpy()
    maker = ex.mode == "maker"
    rows = []
    ii, jj = np.nonzero(o.side)
    busy_i, busy_until = -1, -1
    for i, j in zip(ii, jj):
        if not m.tradable[i]:
            continue
        t = int(o.dec_min[j])
        if i == busy_i and t <= busy_until:
            continue
        side = int(o.side[i, j])
        T = int(min(o.tstop[i, j], n_min))
        if T <= t:
            continue
        px = m.C[i, t - 1]
        # ---------------------------------------------------------------- entry
        if maker:
            limit = px * (1.0 - side * off)
            end = min(t + ex.entry_timeout, T - 1)
            if end <= t:
                continue
            seg = m.L[i, t:end] < limit if side > 0 else m.H[i, t:end] > limit
            k = _first(seg)
            if k < 0:
                continue
            eb, ep, e_mid, e_maker = t + k, limit, limit, True
            k0 = eb + 1
        else:
            eb = t
            e_mid = m.O[i, t]
            ep, e_maker = e_mid * (1.0 + side * slip), False
            k0 = eb
        if k0 >= T:
            k0 = T
        tgt, stp = o.target[i, j], o.stop[i, j]
        if np.isfinite(tgt) and side * (tgt - ep) <= 0:
            tgt = np.nan                   # target already on the wrong side: time stop only
        # ---------------------------------------------------------------- exit events
        # candidates: (event key, exit_bar, price, mid, maker, reason); earliest wins
        cands = []
        Hs, Ls, Cs = m.H[i, k0:T], m.L[i, k0:T], m.C[i, k0:T]
        if np.isfinite(tgt) and T > k0:
            if maker:
                k = _first(Hs > tgt) if side > 0 else _first(Ls < tgt)
                if k >= 0:
                    cands.append((k0 + k, k0 + k, tgt, tgt, True, "target"))
            else:
                k = _first(Cs[:-1] >= tgt) if side > 0 else _first(Cs[:-1] <= tgt)
                if k >= 0:
                    b = k0 + k + 1
                    cands.append((b - 0.5, b, m.O[i, b] * (1 - side * slip), m.O[i, b], False, "target"))
        if np.isfinite(stp) and T - 1 > k0:
            k = _first(Cs[:-1] <= stp) if side > 0 else _first(Cs[:-1] >= stp)
            if k >= 0:
                b = k0 + k + 1
                cands.append((b - 0.5, b, m.O[i, b] * (1 - side * slip), m.O[i, b], False, "stop"))
        # time stop
        ts = None
        if maker:
            s0 = max(T - ex.exit_window, k0)
            if T > s0 and s0 >= 1:
                lim = m.C[i, s0 - 1] * (1.0 + side * off)    # sell above for a long
                seg = m.H[i, s0:T] > lim if side > 0 else m.L[i, s0:T] < lim
                k = _first(seg)
                if k >= 0:
                    ts = (s0 + k, s0 + k, lim, lim, True, "time")
        if ts is None:
            base = m.O[i, T] if T < n_min else m.C[i, n_min - 1]
            ts = (T - 0.5, T, base * (1 - side * slip), base, False, "time")
        # a maker time-stop limit only exists from s0 on; events before it win
        cands.append(ts)
        # key = event time: x - 0.5 = open of bar x (taker), x = during bar x (maker)
        _, xb, xp, x_mid, x_maker, reason = min(cands, key=lambda c: c[0])
        fee = (ex.maker_fee if e_maker else ex.taker_fee) + \
              (ex.maker_fee if x_maker else ex.taker_fee) * xp / ep
        fund = 0.0
        if f_times is not None:
            fund = _funding_cost(m, i, side, 1.0 / ep, eb, min(xb, n_min), f_times, f_rates)
        gross_mid = side * (x_mid / e_mid - 1.0)
        gross = side * (xp / ep - 1.0)
        rows.append(dict(symbol=symbol, date=m.dates[i], sess_idx=i, dec_min=t, side=side,
                         entry_time=m.bar_time(i, eb), exit_time=m.bar_time(i, min(xb, n_min - 1)),
                         entry_bar=eb, exit_bar=xb, entry_px=ep, exit_px=xp,
                         entry_maker=e_maker, exit_maker=x_maker, reason=reason,
                         gross_mid=gross_mid, gross=gross, fees=fee, funding=fund,
                         net=gross - fee - fund))
        busy_i, busy_until = i, xb
    cols = ["symbol", "date", "sess_idx", "dec_min", "side", "entry_time", "exit_time", "entry_bar",
            "exit_bar", "entry_px", "exit_px", "entry_maker", "exit_maker", "reason",
            "gross_mid", "gross", "fees", "funding", "net"]
    return pd.DataFrame(rows, columns=cols)


def session_returns(trades: pd.DataFrame, m: SessionMatrix) -> pd.Series:
    """Net return per session (sum of that session's trades, unit notional); 0 if no trade."""
    r = pd.Series(0.0, index=m.dates)
    if len(trades):
        g = trades.groupby("date")["net"].sum()
        r.loc[g.index] = g.to_numpy()
    return r
