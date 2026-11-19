"""Grid trading engines (event driven over 1-minute OHLC arrays).

Timing convention: bar i covers [t_i, t_i + 1m). Its open/high/low/close are only usable
for decisions taken at or after its close. Resting limit orders placed before bar i may
fill inside bar i if the bar's range reaches them (rule depends on the engine). Market
orders decided at the close of bar i execute at the open of bar i+1 (where stated).

To keep the Python loop short, bars where no order can fill are skipped with a vectorised
search (`find_first`); only candidate bars are processed one by one. The skipping is
exact: a skipped bar provably triggers nothing under the engine's own rules.

Engines
-------
* `dgt_code_replica`  : the authors' published code (github colachenkc/Dynamic-Grid-Trading,
  src/dgt_backtest.py + src/grid_logic.py) transcribed 1:1, including its closed-form profit
  bookkeeping and its "IRR" metric. Two call-signature bugs that make the published code crash
  are fixed (extra `max_price` argument); nothing else is changed.
* `run_dgt`           : explicit lot-by-lot bookkeeping of the DGT strategy, with switchable
  level type (geometric as in the paper text / arithmetic as in the code), fill rule and
  reset timing. Produces an event log for daily marking.
"""
from __future__ import annotations

from bisect import bisect_right

import numpy as np


# ----------------------------------------------------------------------------- search

def find_first(low: np.ndarray, high: np.ndarray, i: int, a: float, b: float,
               low_inclusive: bool = False) -> int:
    """First index j >= i with low[j] < a (or <= a) or high[j] > b. len(low) if none."""
    n = len(low)
    step = 128
    while i < n:
        j = min(n, i + step)
        if low_inclusive:
            m = (low[i:j] <= a) | (high[i:j] > b)
        else:
            m = (low[i:j] < a) | (high[i:j] > b)
        k = int(m.argmax())
        if m[k]:
            return i + k
        i = j
        step = min(step * 4, 1 << 16)
    return n


# ----------------------------------------------------------------------------- authors' code

def dgt_code_replica(o, hi, lo, cl, grid_size: float, half: int, fee: float = 0.0008,
                     principal: float = 100.0, months: int = 43) -> dict:
    """Transcription of the authors' DGT backtest (arithmetic grid, closed-form profits).

    Per bar the code walks the path [prev close (open on bar 0), low, high, close] and counts
    every level crossed (several per bar allowed): up-crossing if start <= level < end,
    down-crossing if end <= level < start. A break (top/bottom level reached or price beyond
    the range) resets the grid centred at the path point where it happened.
    """
    n_g = 2 * half
    per = principal / n_g

    def levels(p):
        d = p * grid_size
        return [p - d * i for i in range(half, 0, -1)] + [p] + [p + d * i for i in range(1, half + 1)]

    def profit_up(hh):
        return (hh * (hh + 1) / 2) * per * (grid_size - fee * 2)

    def profit_arb(hh, tc):
        return ((tc - hh) / 2) * per * (grid_size - fee * 2)

    def fund(usdt, money_input):
        if usdt >= principal:
            return usdt - principal, money_input
        return 0.0, money_input + (principal - usdt)

    usdt, coin, trade_count, money_input = 0.0, 0.0, 0, principal
    init = float(o[0])
    L = levels(init)
    cur = half
    n_up = n_dn = 0
    N = len(cl)
    i = 0
    while i < N:
        if i > 0:
            i = find_first(lo, hi, i, L[cur - 1], L[cur + 1], low_inclusive=True)
            if i >= N:
                break
        pts = (float(o[0]) if i == 0 else float(cl[i - 1]), float(lo[i]), float(hi[i]), float(cl[i]))
        for s in range(3):
            sp, ep = pts[s], pts[s + 1]
            if sp < ep:
                while cur < n_g and sp <= L[cur + 1] < ep:
                    cur += 1
                    trade_count += 1
            else:
                while cur > 0 and ep <= L[cur - 1] < sp:
                    cur -= 1
                    trade_count += 1
            if ep > L[-1] or cur == n_g:
                usdt += profit_up(half) + profit_arb(half, trade_count) + principal
                trade_count = 0
                usdt, money_input = fund(usdt, money_input)
                init = ep
                L = levels(init)
                cur = half
                n_up += 1
            if ep < L[0] or cur == 0:
                usdt += profit_arb(half, trade_count)
                coin += (principal / 2) / init * (1 - fee * 2)
                for q in range(half):
                    coin += per / L[q] * (1 - fee * 2)
                trade_count = 0
                usdt, money_input = fund(usdt, money_input)
                init = ep
                L = levels(init)
                cur = half
                n_dn += 1
        i += 1

    # settle_last_grid_segment (verbatim logic)
    close = float(cl[-1])
    mid_idx, mid_price = half, L[half]
    mid_coin = (principal / 2) / mid_price * (1 - fee)
    idx = bisect_right(L, close) - 1
    if close >= mid_price:
        remain = n_g - idx
        usdt += remain * per
        up = max(0, idx - mid_idx)
        usdt += up * per + profit_up(up) + profit_arb(up, trade_count)
        coin += mid_coin * (remain / half)
    else:
        down = max(0, mid_idx - idx)
        for j in range(mid_idx - 1, idx, -1):
            coin += (per / L[j]) * (1 - fee * 2)
        usdt += profit_arb(down, trade_count)
        usdt += (half - down) * per
        coin += mid_coin
    total = usdt + coin * close
    return dict(grid_size=grid_size, half=half, usdt=usdt, coin=coin, total_value=total,
                money_input=money_input, profit=total - money_input,
                ratio=total / money_input,
                irr_code=(total / money_input) ** (12 / months) - 1,
                n_up_resets=n_up, n_down_resets=n_dn)


# ----------------------------------------------------------------------------- explicit DGT

class DGTLog:
    """Event log of the explicit DGT engine (state after processing bar `bar`)."""

    def __init__(self):
        self.bar, self.cash, self.coins, self.money_in = [], [], [], []
        self.realized, self.fees, self.bag = [], [], []
        self.injections = []          # (bar, amount)
        self.resets = []              # (bar, 'up'|'down')
        self.n_fills = 0

    def arrays(self):
        return {k: np.asarray(getattr(self, k)) for k in
                ("bar", "cash", "coins", "money_in", "realized", "fees", "bag")}


def run_dgt(o, hi, lo, cl, grid_size: float, half: int, fee: float = 0.0008,
            principal: float = 100.0, levels: str = "geo", fill: str = "through",
            reset: str = "next_open", both_rule: str = "ohlc", max_fills: int = 1) -> DGTLog:
    """Explicit DGT simulation.

    Grid: n = 2*half grids, levels P*(1+k)^j (geo) or P*(1+k*j) (arith), j = -half..half.
    Sizing (paper 1.1.1-1.1.2 / authors' code): at start buy principal/2 of coin (split into
    `half` equal sell lots for the upper levels) and keep principal/2 as `half` buy orders of
    principal/n each. A buy at level m spends principal/n and places a sell lot at m+1; a sell
    at level m sells that lot, returns principal/n to a buy order at m-1 and sweeps the profit
    to the wallet (the paper's "wallet ... cumulative profits from grid arbitrage").
    DGT reset (paper 3.1 + code `fund_next_grid`): top level filled -> all coin sold, the
    principal returns to the wallet; bottom level filled -> the coins are kept forever in a
    "bag". Either way a new grid centred at the current price is funded with `principal`
    from the wallet, and any shortfall is injected as new external capital.

    fill:  'through' -> sell fills iff high > level, buy iff low < level (strict trade-through);
           'touch'   -> sell iff high > level, buy iff low <= level (the authors' code rule).
    max_fills: fills per bar (the paper: at most one transaction per minute).
    both_rule: if both a buy and a sell are reachable in one bar, which comes first:
           'low_first' (authors' path open->low->high->close) or 'ohlc' (low first iff close>=open).
           'code_path' replaces the whole per-bar logic by the authors' path walk (unlimited
           fills per bar, touch rule, reset at the breaking path point); used to cross-check
           `dgt_code_replica` with explicit bookkeeping.
    reset: 'close' -> new grid at the close of the bar where the break filled;
           'next_open' -> at the open of the next bar (market order decided at the close).
    Every trade pays `fee` (the paper's 0.08%).
    """
    n_g = 2 * half
    per = principal / n_g
    N = len(cl)
    js = np.arange(-half, half + 1, dtype=np.float64)
    log = DGTLog()
    st = dict(wallet=0.0, bag=0.0, money_in=0.0, realized=0.0, fees=0.0, c=half)
    lot = np.zeros(n_g + 1)
    Lv = None
    active = False

    def mk(p):
        return p * (1 + grid_size) ** js if levels == "geo" else p * (1 + grid_size * js)

    def start(p, bar):
        nonlocal Lv, active
        if st["wallet"] >= principal:
            st["wallet"] -= principal
        else:
            need = principal - st["wallet"]
            st["money_in"] += need
            st["wallet"] = 0.0
            log.injections.append((bar, need))
        spend = principal / 2
        coins = spend * (1 - fee) / p
        st["fees"] += spend * fee
        lot[:] = 0.0
        lot[half + 1:] = coins / half
        st["c"] = half
        Lv = mk(p)
        active = True

    def record(bar):
        c = st["c"]
        grid_cash = c * per if active else 0.0
        grid_coins = lot[c + 1:].sum() if active else 0.0
        log.bar.append(bar)
        log.cash.append(st["wallet"] + grid_cash)
        log.coins.append(st["bag"] + grid_coins)
        log.money_in.append(st["money_in"])
        log.realized.append(st["realized"])
        log.fees.append(st["fees"])
        log.bag.append(st["bag"])

    def sell(bar):
        nonlocal active
        c = st["c"]
        m = c + 1
        gross = lot[m] * Lv[m]
        st["fees"] += gross * fee
        prof = gross * (1 - fee) - per
        st["wallet"] += prof
        st["realized"] += prof
        lot[m] = 0.0
        st["c"] = m
        log.n_fills += 1
        if m == n_g:
            st["wallet"] += principal      # grid holds only USDT = principal
            active = False
            log.resets.append((bar, "up"))

    def buy(bar):
        nonlocal active
        c = st["c"]
        m = c - 1
        st["fees"] += per * fee
        lot[c] = per * (1 - fee) / Lv[m]
        st["c"] = m
        log.n_fills += 1
        if m == 0:
            st["bag"] += lot[1:].sum()
            lot[:] = 0.0
            active = False
            log.resets.append((bar, "down"))

    start(float(o[0]), 0)
    record(0)
    i = 0
    low_incl = fill == "touch"
    pending_reset = False
    while i < N:
        if pending_reset:
            start(float(o[i]), i)
            pending_reset = False
        else:
            c = st["c"]
            j = find_first(lo, hi, i, Lv[c - 1], Lv[c + 1], low_inclusive=low_incl)
            if j >= N:
                break
            i = j
        if both_rule == "code_path":
            # authors' path walk: [prev close, low, high, close], every crossing fills,
            # a break resets the grid at the path point where it happened
            pts = (float(o[0]) if i == 0 else float(cl[i - 1]), float(lo[i]), float(hi[i]), float(cl[i]))
            for s_ in range(3):
                sp, ep = pts[s_], pts[s_ + 1]
                if sp < ep:
                    while active and sp <= Lv[st["c"] + 1] < ep:
                        sell(i)
                else:
                    while active and ep <= Lv[st["c"] - 1] < sp:
                        buy(i)
                if not active:
                    start(ep, i)
            record(i)
            i += 1
            continue
        n_done = 0
        while active and n_done < max_fills:
            c = st["c"]
            can_sell = hi[i] > Lv[c + 1]
            can_buy = (lo[i] <= Lv[c - 1]) if low_incl else (lo[i] < Lv[c - 1])
            if not (can_sell or can_buy):
                break
            if can_sell and can_buy:
                low_first = True if both_rule == "low_first" else (cl[i] >= o[i])
                (buy if low_first else sell)(i)
            elif can_buy:
                buy(i)
            else:
                sell(i)
            n_done += 1
        if not active:
            if reset == "close":
                start(float(cl[i]), i)
            else:
                pending_reset = True
        record(i)
        i += 1
    return log


def mark_to_market(log: DGTLog, cl: np.ndarray, bars: np.ndarray) -> dict:
    """State at the close of each bar in `bars` (e.g. the last bar of each day)."""
    a = log.arrays()
    k = np.searchsorted(a["bar"], bars, side="right") - 1
    px = cl[bars]
    cash, coins = a["cash"][k], a["coins"][k]
    return dict(equity=cash + coins * px, cash=cash, coins=coins, money_in=a["money_in"][k],
                realized=a["realized"][k], fees=a["fees"][k], bag=a["bag"][k], px=px)
