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


def greedy_targets(bundle, rule: GreedyRule, start: str | None = None) -> tuple[dict[int, list], pd.DataFrame]:
    """Daily 00:00 UTC decisions. Returns ({bar: target list}, log of each decision)."""
    m = bundle.market
    idx = m.index
    rows = np.flatnonzero((idx.hour == 0) & (idx.minute == 0))
    if start is not None:
        rows = rows[idx[rows] >= pd.Timestamp(start, tz="UTC")]
    hist = rule.min_history_days * 24
    first = np.maximum(_first_valid(m.spot), _first_valid(m.perp))
    win = int(round(rule.signal_days * 24))
    csum = np.vstack([np.zeros((1, m.funding.shape[1])), np.cumsum(m.funding, axis=0)])
    cnt = np.vstack([np.zeros((1, m.funding.shape[1])), np.cumsum(m.funding != 0, axis=0)])
    qw = rule.qv_window_days * 24
    med_s = rolling_median(bundle.spot_qv.astype(float), qw, rows)
    med_p = rolling_median(bundle.perp_qv.astype(float), qw, rows)
    sym = np.array(m.symbols)
    targets, log, held = {}, [], []
    for i, t in enumerate(rows):
        sig = (csum[t + 1] - csum[max(0, t + 1 - win)]) / rule.signal_days
        has = (cnt[t + 1] - cnt[max(0, t + 1 - win)]) > 0
        ok = ((t - first) >= hist) & np.isfinite(m.spot[t]) & np.isfinite(m.perp[t]) & has \
            & (med_s[i] >= rule.min_spot_qv) & (med_p[i] >= rule.min_perp_qv)
        if rule.top_n_liquidity is not None and ok.any():
            liq = np.where(ok, med_p[i], -np.inf)
            order = np.lexsort((sym, -liq))
            top = np.zeros_like(ok)
            top[order[:min(rule.top_n_liquidity, ok.sum())]] = True
            ok &= top
        cand = np.flatnonzero(ok)
        ranked = cand[np.lexsort((sym[cand], -sig[cand]))]          # signal desc, ties by symbol
        rank = {j: r + 1 for r, j in enumerate(ranked)}
        if rule.keep_rank is None:
            chosen = list(ranked[:rule.k])
        else:
            keep = [j for j in held if j in rank and rank[j] <= rule.keep_rank and sig[j] > 0]
            keep = sorted(keep, key=lambda j: rank[j])[:rule.k]
            new = [j for j in ranked if j not in keep and
                   (rule.entry_threshold is None or sig[j] >= rule.entry_threshold)]
            chosen = keep + new[:rule.k - len(keep)]
        held = chosen
        targets[int(t)] = [m.symbols[j] for j in chosen]
        log.append({"time": idx[t], "n_eligible": int(ok.sum()), "n_chosen": len(chosen),
                    "mean_signal": float(np.mean(sig[chosen])) if chosen else np.nan,
                    "chosen": ",".join(m.symbols[j] for j in chosen)})
    return targets, pd.DataFrame(log)
