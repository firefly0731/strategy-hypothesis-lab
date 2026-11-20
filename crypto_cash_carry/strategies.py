"""Target sets for the engine (DESIGN.md §4). Everything at decision bar t uses rows ≤ t only."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .engine import Band, Costs


def fixed_targets(index: pd.DatetimeIndex, symbols, entry: str) -> dict[int, list]:
    j = index.get_loc(pd.Timestamp(entry, tz="UTC"))
    return {j: list(symbols)}


@dataclass(frozen=True)
class GreedyRule:
    k: int = 10
    signal_days: float = 1.0            # trailing funding window; signal = sum / days (per day)
    min_history_days: int = 30
    min_spot_qv: float = 1e5            # 30D median hourly quote volume
    min_perp_qv: float = 1e5
    top_n_liquidity: int | None = None
    entry_threshold: float | None = None  # per-day signal a NEW name needs
    keep_rank: int | None = None        # held names stay while rank ≤ keep_rank and signal > 0
    qv_window_days: int = 30

    @staticmethod
    def spec() -> "GreedyRule":
        return GreedyRule()

    @staticmethod
    def improved(costs: Costs = Costs(), band: Band = Band(), hold_days: int = 7) -> "GreedyRule":
        round_trip = 2 * (band.spot_frac * costs.c_s + band.short_frac * costs.c_p)
        return GreedyRule(signal_days=3.0, min_history_days=365, min_perp_qv=1e6, top_n_liquidity=40,
                          entry_threshold=round_trip / (band.short_frac * hold_days), keep_rank=20)


def _first_valid(a: np.ndarray) -> np.ndarray:
    ok = np.isfinite(a)
    first = np.where(ok.any(axis=0), ok.argmax(axis=0), a.shape[0])
    return first


def rolling_median(a: np.ndarray, bars: int, rows: np.ndarray) -> np.ndarray:
    """Median over the trailing `bars` rows ending at each row in `rows` (NaNs ignored, ≥ 80% present)."""
    out = np.full((len(rows), a.shape[1]), np.nan)
    for i, r in enumerate(rows):
        w = a[max(0, r - bars + 1): r + 1]
        cnt = np.isfinite(w).sum(axis=0)
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                med = np.nanmedian(w, axis=0)
        out[i] = np.where(cnt >= 0.8 * bars, med, np.nan)
    return out


class GreedySelector:
    """Daily 00:00 UTC decisions (DESIGN.md §4.B/C). Call (t, held) -> target list | None.

    `held` is what the engine really holds, so the buffer rule and the entry threshold apply to the
    true book. Everything at bar t uses rows ≤ t only.
    """

    def __init__(self, bundle, rule: "GreedyRule", start: str | None = None):
        m = bundle.market
        self.m, self.rule = m, rule
        idx = m.index
        rows = np.flatnonzero((idx.hour == 0) & (idx.minute == 0))
        if start is not None:
            rows = rows[idx[rows] >= pd.Timestamp(start, tz="UTC")]
        self.rows = rows
        self.row_pos = {int(t): i for i, t in enumerate(rows)}
        self.first = np.maximum(_first_valid(m.spot), _first_valid(m.perp))
        self.win = int(round(rule.signal_days * 24))
        self.csum = np.vstack([np.zeros((1, m.funding.shape[1])), np.cumsum(m.funding, axis=0)])
        self.cnt = np.vstack([np.zeros((1, m.funding.shape[1])), np.cumsum(m.funding != 0, axis=0)])
        qw = rule.qv_window_days * 24
        self.med_s = rolling_median(bundle.spot_qv.astype(float), qw, rows)
        self.med_p = rolling_median(bundle.perp_qv.astype(float), qw, rows)
        self.sym = np.array(m.symbols)
        self.col = {x: j for j, x in enumerate(m.symbols)}
        self.log = []

    def __call__(self, t: int, held) -> list | None:
        i = self.row_pos.get(int(t))
        if i is None:
            return None
        m, rule, sym = self.m, self.rule, self.sym
        lo = max(0, t + 1 - self.win)
        # rounded: the cumsum difference carries ~1e-18 noise that would break exact ties
        sig = np.round((self.csum[t + 1] - self.csum[lo]) / rule.signal_days, 12)
        has = (self.cnt[t + 1] - self.cnt[lo]) > 0
        base = ((t - self.first) >= rule.min_history_days * 24) & np.isfinite(m.spot[t]) & np.isfinite(m.perp[t])
        if rule.top_n_liquidity is not None and base.any():     # top-N of the history-eligible names first
            liq = np.where(base & np.isfinite(self.med_p[i]), self.med_p[i], -np.inf)
            order = np.lexsort((sym, -liq))
            top = np.zeros_like(base)
            top[order[:min(rule.top_n_liquidity, int(base.sum()))]] = True
            base &= top
        ok = base & has & (self.med_s[i] >= rule.min_spot_qv) & (self.med_p[i] >= rule.min_perp_qv)
        cand = np.flatnonzero(ok)
        ranked = cand[np.lexsort((sym[cand], -sig[cand]))]       # signal desc, ties by symbol
        rank = {int(j): r + 1 for r, j in enumerate(ranked)}
        held_j = [self.col[x] for x in held if x in self.col]
        if rule.keep_rank is None:
            chosen = [int(j) for j in ranked[:rule.k]]
        else:
            keep = sorted((j for j in held_j if j in rank and rank[j] <= rule.keep_rank and sig[j] > 0),
                          key=lambda j: rank[j])[:rule.k]
            new = [int(j) for j in ranked if j not in keep and
                   (rule.entry_threshold is None or sig[j] >= rule.entry_threshold)]
            chosen = keep + new[:rule.k - len(keep)]
        self.log.append({"time": m.index[t], "n_eligible": int(ok.sum()), "n_chosen": len(chosen),
                         "mean_signal": float(np.mean(sig[chosen])) if chosen else np.nan,
                         "chosen": ",".join(m.symbols[j] for j in chosen)})
        return [m.symbols[j] for j in chosen]


def greedy_targets(bundle, rule: GreedyRule, start: str | None = None) -> tuple[dict[int, list], pd.DataFrame]:
    """Stand-alone decisions assuming every chosen name is held (tests, quick looks). The backtest
    passes a GreedySelector to the engine instead, so `held` is the engine's real book."""
    sel = GreedySelector(bundle, rule, start)
    held, targets = [], {}
    for t in sel.rows:
        held = sel(int(t), held)
        targets[int(t)] = held
    return targets, pd.DataFrame(sel.log)
