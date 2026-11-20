"""Cash-and-carry accounting engine: spot long + short perp sleeves (DESIGN.md §2–3).

Every sleeve is (qs spot coins, qp short perp coins, M futures-account equity). Per bar, in order:
intrabar liquidation check → mark to market → funding → trades at the close (exits, band
rebalances, entries). The portfolio identity E_t − E_{t−1} = spot + perp + funding − fee − slip − liq
is asserted at every bar.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Costs:
    spot_fee: float = 0.0010
    perp_fee: float = 0.0005
    slippage: float = 0.0002          # per side, both legs

    @property
    def c_s(self) -> float:
        return self.spot_fee + self.slippage

    @property
    def c_p(self) -> float:
        return self.perp_fee + self.slippage


@dataclass(frozen=True)
class Band:
    spot_frac: float = 0.75           # spot notional per $ of sleeve; margin = 1 − spot_frac
    target: float = 3.0               # qp·F / M after a trade
    lo: float = 2.0
    hi: float = 5.0

    @property
    def short_frac(self) -> float:
        return self.target * (1 - self.spot_frac)


@dataclass
class Market:
    index: pd.DatetimeIndex           # hourly bar CLOSE times, UTC
    symbols: list
    spot: np.ndarray                  # (N, S) closes, NaN = no trade in that bar
    perp: np.ndarray                  # (N, S) closes, per coin (multiplier removed)
    liq_high: np.ndarray              # (N, S) intrabar high of the liquidation price (mark), per coin
    funding: np.ndarray               # (N, S) summed settlement rates in (t_{j-1}, t_j], 0 = none
    mmr: np.ndarray                   # (S,) maintenance margin rate

    def __post_init__(self):
        n, s = len(self.index), len(self.symbols)
        for name in ("spot", "perp", "liq_high", "funding"):
            a = getattr(self, name)
            assert a.shape == (n, s), f"{name} shape {a.shape} != {(n, s)}"
            assert not np.isinf(a).any(), f"{name} has inf"
        assert np.isfinite(self.funding).all(), "funding must be 0 where there is no settlement"
        for name in ("spot", "perp", "liq_high"):
            a = getattr(self, name)
            assert (a[np.isfinite(a)] > 0).all(), f"{name} has non-positive prices"
        assert self.index.tz is not None and str(self.index.tz) == "UTC"
        assert self.index.is_monotonic_increasing and self.index.is_unique


@dataclass
class SimResult:
    bars: pd.DataFrame
    trades: pd.DataFrame
    by_symbol: pd.DataFrame
    state_after: list | None = None
    stats: dict = field(default_factory=dict)

    @property
    def n_rebalances(self) -> int:
        return int(self.bars["n_rebal"].sum())


COLS = ("equity", "cash", "spot_pnl", "perp_pnl", "funding", "fee", "slippage", "liq_loss",
        "n_rebal", "n_liq", "n_entries", "n_exits", "n_active", "traded")


def _solve_post_cost(e: float, a: float, b: float, costs: Costs, band: Band) -> float:
    """e' = e − c_s|f_s e' − a| − c_p|f_p e' − b| by fixed-point iteration (contraction)."""
    x = e
    for _ in range(50):
        nxt = e - costs.c_s * abs(band.spot_frac * x - a) - costs.c_p * abs(band.short_frac * x - b)
        if abs(nxt - x) <= 1e-16 * max(1.0, abs(e)):
            return nxt
        x = nxt
    return x


def simulate(m: Market, targets: dict[int, list], slots: int, costs: Costs = Costs(), band: Band = Band(),
             initial: float = 1.0, close_at_end: bool = True, check_liq: bool = True,
             record_state: bool | None = None) -> SimResult:
    """targets: {bar index: desired set of symbols}. Names leaving the set are exited, new names are
    entered at min(E/slots, cash/n_new) each, names that stay keep their sleeve (band only)."""
    N, S = m.spot.shape
    col = {s: i for i, s in enumerate(m.symbols)}
    if record_state is None:
        record_state = N <= 5000
    last_spot = np.full(S, -1)
    last_perp = np.full(S, -1)
    for j in range(S):
        ok_s = np.flatnonzero(np.isfinite(m.spot[:, j]))
        ok_p = np.flatnonzero(np.isfinite(m.perp[:, j]))
        last_spot[j] = ok_s[-1] if len(ok_s) else -1
        last_perp[j] = ok_p[-1] if len(ok_p) else -1

    cash = float(initial)
    sl: dict[int, dict] = {}                   # j -> {qs, qp, M, S, F}  (S, F = last marked prices)
    rec = np.zeros((N, len(COLS)))
    trades = []
    per_sym = np.zeros((S, 5))                 # funding, basis (spot+perp pnl), fee, slip, liq
    states = [] if record_state else None
    E_prev = cash
    min_ratio = (np.inf, None, None)            # worst intrabar M / (qp·H) on the mark high

    def mark(j, s):
        return s["qs"] * s["S"] + s["M"]

    def trade(t, j, s, new_qs, new_qp, kind, out):
        dspot = abs(new_qs - s["qs"]) * s["S"]
        dperp = abs(new_qp - s["qp"]) * s["F"]
        fee = costs.spot_fee * dspot + costs.perp_fee * dperp
        slip = costs.slippage * (dspot + dperp)
        out["fee"] += fee
        out["slippage"] += slip
        out["traded"] += dspot + dperp
        per_sym[j, 2] += fee
        per_sym[j, 3] += slip
        trades.append((m.index[t], m.symbols[j], kind, dspot, dperp, fee, slip))
        return fee + slip

    for t in range(N):
        out = dict.fromkeys(COLS, 0.0)
        sp, pp, hp, fr = m.spot[t], m.perp[t], m.liq_high[t], m.funding[t]
        for j, s in list(sl.items()):
            # 1. intrabar liquidation on the mark-price high
            if check_liq and s["qp"] > 0 and np.isfinite(hp[j]):
                worst = s["M"] - s["qp"] * (hp[j] - s["F"])
                ratio = worst / (s["qp"] * hp[j])
                if ratio < min_ratio[0]:
                    min_ratio = (ratio, m.index[t], m.symbols[j])
                if worst <= m.mmr[j] * s["qp"] * hp[j]:
                    p_liq = (s["M"] + s["qp"] * s["F"]) / (s["qp"] * (1 + m.mmr[j]))
                    pnl = -s["qp"] * (p_liq - s["F"])
                    loss = m.mmr[j] * s["qp"] * p_liq
                    out["perp_pnl"] += pnl
                    out["liq_loss"] += loss
                    out["n_liq"] += 1
                    per_sym[j, 1] += pnl
                    per_sym[j, 4] += loss
                    s["M"] += pnl - loss
                    assert abs(s["M"]) <= 1e-12 * max(1.0, s["qp"] * p_liq), s["M"]
                    s["M"] = 0.0
                    trades.append((m.index[t], m.symbols[j], "liquidation", 0.0, s["qp"] * p_liq, 0.0, 0.0))
                    s["qp"] = 0.0
                    s["F"] = p_liq
            # 2. mark to market (missing prices: hold at the last valid price)
            if np.isfinite(sp[j]):
                d = s["qs"] * (sp[j] - s["S"])
                out["spot_pnl"] += d
                per_sym[j, 1] += d
                s["S"] = sp[j]
            if np.isfinite(pp[j]):
                d = -s["qp"] * (pp[j] - s["F"])
                out["perp_pnl"] += d
                per_sym[j, 1] += d
                s["M"] += d
                s["F"] = pp[j]
            # 3. funding on the position held through the bar (short receives qp·F·r)
            if fr[j] != 0.0 and s["qp"] > 0:
                f = s["qp"] * s["F"] * fr[j]
                out["funding"] += f
                per_sym[j, 0] += f
                s["M"] += f

        # 4. trades at the close
        want = targets.get(t)
        for j, s in list(sl.items()):
            delisted = min(last_spot[j], last_perp[j]) < N - 1 and t >= min(last_spot[j], last_perp[j])
            fresh = np.isfinite(sp[j]) and np.isfinite(pp[j])
            leave = want is not None and m.symbols[j] not in want and fresh   # no trades at stale prices
            if close_at_end and t == N - 1 or delisted or leave:
                trade(t, j, s, 0.0, 0.0, "exit", out)
                cash += s["qs"] * s["S"] * (1 - costs.c_s) + s["M"] - costs.c_p * s["qp"] * s["F"]
                del sl[j]
                out["n_exits"] += 1
        for j, s in sl.items():
            if not (np.isfinite(sp[j]) and np.isfinite(pp[j])):
                continue
            lev = s["qp"] * s["F"] / s["M"] if s["M"] > 0 else np.inf
            if band.lo <= lev <= band.hi:
                continue
            e = mark(j, s)
            e1 = _solve_post_cost(e, s["qs"] * s["S"], s["qp"] * s["F"], costs, band)
            nqs, nqp = band.spot_frac * e1 / s["S"], band.short_frac * e1 / s["F"]
            c = trade(t, j, s, nqs, nqp, "rebalance", out)
            s.update(qs=nqs, qp=nqp, M=e1 - band.spot_frac * e1)
            assert abs((e - c) - e1) <= 1e-12 * max(1.0, e)
            out["n_rebal"] += 1
        if want is not None and not (close_at_end and t == N - 1):
            new = [col[x] for x in want if x in col and col[x] not in sl
                   and np.isfinite(sp[col[x]]) and np.isfinite(pp[col[x]])
                   and (t < min(last_spot[col[x]], last_perp[col[x]]) or min(last_spot[col[x]], last_perp[col[x]]) == N - 1)]
            if new:
                E_now = cash + sum(mark(j, s) for j, s in sl.items())
                per = min(E_now / slots, cash / len(new))
                for j in new:
                    if per <= 0:
                        break
                    e1 = per / (1 + band.spot_frac * costs.c_s + band.short_frac * costs.c_p)
                    s = dict(qs=0.0, qp=0.0, M=0.0, S=sp[j], F=pp[j])
                    nqs, nqp = band.spot_frac * e1 / sp[j], band.short_frac * e1 / pp[j]
                    trade(t, j, s, nqs, nqp, "entry", out)
                    s.update(qs=nqs, qp=nqp, M=e1 - band.spot_frac * e1)
                    sl[j] = s
                    cash -= per
                    out["n_entries"] += 1
                if abs(cash) < 1e-12:
                    cash = 0.0
        E = cash + sum(mark(j, s) for j, s in sl.items())
        out["equity"], out["cash"], out["n_active"] = E, cash, len(sl)
        flows = out["spot_pnl"] + out["perp_pnl"] + out["funding"] - out["fee"] - out["slippage"] - out["liq_loss"]
        assert np.isfinite(E) and cash >= -1e-12, (t, E, cash)
        assert abs(E - E_prev - flows) <= 1e-9 * max(1.0, abs(E)), (m.index[t], E - E_prev, flows)
        E_prev = E
        rec[t] = [out[c] for c in COLS]
        if record_state:
            states.append({m.symbols[j]: dict(s) for j, s in sl.items()})

    bars = pd.DataFrame(rec, index=m.index, columns=list(COLS))
    tr = pd.DataFrame(trades, columns=["time", "symbol", "kind", "spot_notional", "perp_notional", "fee", "slippage"])
    by = pd.DataFrame(per_sym, index=m.symbols, columns=["funding", "basis", "fee", "slippage", "liq_loss"])
    by = by[(by != 0).any(axis=1)]
    stats = {"min_margin_ratio": min_ratio[0], "min_margin_time": min_ratio[1], "min_margin_symbol": min_ratio[2]}
    return SimResult(bars=bars, trades=tr, by_symbol=by, state_after=states, stats=stats)
