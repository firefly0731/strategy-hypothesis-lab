"""Passive two-sided maker on 1-minute bars (DESIGN.md "Maker model").

Prices are passed normalised by each session's open, so one unit = 1 coin = notional 1 at the
open and PnL comes out in fractions of that notional.
"""
from __future__ import annotations

import numpy as np
from numba import njit

ANCHOR, MID = 0, 1


@njit(cache=True)
def simulate(O, H, L, C, allow_bid, allow_ask, flat, delta, mode, cap, taker):
    """Returns (eq, n_fills). eq[s, k] = cash + q * C[s, k] after bar k; the last bar of every
    session includes the taker flatten, so eq[s, -1] is the session's realised PnL."""
    n_s, n_k = C.shape
    eq = np.zeros((n_s, n_k))
    n_fills = np.zeros((n_s, n_k), dtype=np.int64)
    up, dn = 1.0 + delta, 1.0 - delta
    for s in range(n_s):
        q = 0
        cash = 0.0
        a = O[s, 0]
        for k in range(n_k):
            prev = C[s, k - 1] if k > 0 else O[s, 0]
            if flat[s, k] and q != 0:
                px = O[s, k]
                cash += q * px - abs(q) * px * taker
                q = 0
            if q == 0:
                a = prev
            if mode == ANCHOR:
                bid = a * dn
                while bid >= prev:
                    bid *= dn
                ask = a * up
                while ask <= prev:
                    ask *= up
            else:
                bid = prev * dn
                ask = prev * up
            buy = allow_bid[s, k] and q < cap and L[s, k] < bid
            sell = allow_ask[s, k] and q > -cap and H[s, k] > ask
            if buy:
                q += 1
                cash -= bid
            if sell:
                q -= 1
                cash += ask
            if buy and not sell:
                a = bid
            elif sell and not buy:
                a = ask
            n_fills[s, k] = int(buy) + int(sell)
            eq[s, k] = cash + q * C[s, k]
        if q != 0:
            px = C[s, n_k - 1]
            cash += q * px - abs(q) * px * taker
            eq[s, n_k - 1] = cash
    return eq, n_fills
