"""Market-neutral (symmetric) perp grid with a stop-and-recentre rule.

Rules (fixed before any result was computed):
* Levels L_m = C * (1+k)^(m-h), m = 0..2h around the centre C. State c (0..2h); position =
  (h - c) units: long below the centre, short above, flat at the centre.
* Capital 1 (USDT). One unit = 1/h of capital in notional at the centre price, i.e.
  q = (1/h)/C coins, so the maximum gross notional is 1x capital (leverage <= ~1).
* Resting post-only limit orders at EVERY level: buys at all levels below c, sells at all
  levels above c (the standard grid ladder). Inside bar i an order fills only if the bar
  trades THROUGH it (buy: low < level; sell: high > level), at the level price, maker fee.
  Each level fills at most once per bar: replacement orders are placed at the bar close
  (a conservative simplification: intrabar re-fills are ignored). Because each level fills
  at most once, the result does not depend on the intrabar path.
* Stop: if a bar CLOSES more than one grid step beyond the outermost level
  (close > L_2h (1+k) or close < L_0/(1+k)), the position is closed at the next bar's open
  with a taker order (fee + slippage) and a new grid is centred at that open.
* Funding: at each settlement the position held pays -pos * mark * rate, mark = close of the
  bar that ends at the settlement time.
"""
from __future__ import annotations

import numpy as np

from .engine import find_first


class NeutralLog:
    def __init__(self):
        self.bar, self.cash, self.pos, self.fees = [], [], [], []
        self.n_fills = 0
        self.stops = []

    def arrays(self):
        return {k: np.asarray(getattr(self, k)) for k in ("bar", "cash", "pos", "fees")}


def run_neutral(o, hi, lo, cl, k: float, h: int, maker: float = 0.0002, taker: float = 0.0005,
                slip: float = 0.0001, fill: str = "through") -> NeutralLog:
    """fill='through' (default, realistic) or 'touch' (optimistic bound: low <= level / high >= level)."""
    touch = fill == "touch"
    N = len(cl)
    js = np.arange(-h, h + 1, dtype=np.float64)
    log = NeutralLog()
    cash = pos = fees = 0.0
    c = h
    L = q = up_stop = dn_stop = None

    def centre(p):
        nonlocal L, q, up_stop, dn_stop, c
        L = p * (1 + k) ** js
        q = (1.0 / h) / p
        up_stop = L[-1] * (1 + k)
        dn_stop = L[0] / (1 + k)
        c = h

    centre(float(o[0]))
    log.bar.append(0); log.cash.append(0.0); log.pos.append(0.0); log.fees.append(0.0)
    i = 0
    pending_stop = False
    n2 = 2 * h
    while i < N:
        if pending_stop:
            p = float(o[i])
            if pos != 0.0:
                px = p * (1 - slip) if pos > 0 else p * (1 + slip)
                cash += pos * px
                f = abs(pos) * px * taker
                cash -= f
                fees += f + abs(pos) * p * slip
                pos = 0.0
            log.stops.append(i)
            centre(p)
            pending_stop = False
        else:
            a = L[c - 1] if c > 0 else dn_stop
            b = L[c + 1] if c < n2 else up_stop
            j = find_first(lo, hi, i, a, b * (1 - 1e-12) if touch else b, low_inclusive=touch)
            if j >= N:
                break
            i = j
        # ladder fills
        first_above_low = int(np.searchsorted(L, lo[i], side="left" if touch else "right"))  # levels > low
        nb = max(0, c - first_above_low)
        first_ge_high = int(np.searchsorted(L, hi[i], side="right" if touch else "left"))  # levels < high
        ns = max(0, first_ge_high - (c + 1))
        if nb:
            px = L[c - nb:c]
            notional = q * px.sum()
            cash -= notional * (1 + maker)
            fees += notional * maker
        if ns:
            px = L[c + 1:c + 1 + ns]
            notional = q * px.sum()
            cash += notional * (1 - maker)
            fees += notional * maker
        if nb or ns:
            pos += q * (nb - ns)
            c += ns - nb
            log.n_fills += nb + ns
        if cl[i] > up_stop or cl[i] < dn_stop:
            pending_stop = True
        log.bar.append(i); log.cash.append(cash); log.pos.append(pos); log.fees.append(fees)
        i += 1
    return log


def daily_pnl(log: NeutralLog, cl: np.ndarray, last: np.ndarray, fund_bar: np.ndarray | None = None,
              fund_rate: np.ndarray | None = None) -> dict:
    """Daily P&L (fraction of capital): net (fees + funding), gross (no fees, no funding),
    plus the funding and fee components. `last` = positions of the last bar of each day.
    fund_bar = position of the bar whose close coincides with each funding settlement."""
    a = log.arrays()
    kk = np.searchsorted(a["bar"], last, side="right") - 1
    eq = a["cash"][kk] + a["pos"][kk] * cl[last]
    fee_c = a["fees"][kk]
    pnl_ex = np.diff(np.r_[0.0, eq])
    fee_d = np.diff(np.r_[0.0, fee_c])
    fund_d = np.zeros(len(last))
    if fund_bar is not None and len(fund_bar):
        kf = np.searchsorted(a["bar"], fund_bar, side="right") - 1
        posf = np.where(kf >= 0, a["pos"][np.maximum(kf, 0)], 0.0)
        fpnl = -posf * cl[fund_bar] * fund_rate
        day_of = np.searchsorted(last, fund_bar, side="left")
        ok = day_of < len(last)
        np.add.at(fund_d, day_of[ok], fpnl[ok])
    return dict(net=pnl_ex + fund_d, gross=pnl_ex + fee_d, fees=fee_d, funding=fund_d,
                ex_funding=pnl_ex)
