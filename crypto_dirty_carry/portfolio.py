"""Target weights at one decision time: baskets → inverse vol → dollar neutral → factor neutral.

Weights are fractions of equity, signed (+ long, - short). Every function here works on a Snapshot,
so nothing after the decision time can enter a target.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import StrategyConfig, td
from .data import Snapshot
from .factors import estimate_betas, funding_carry, rolling_vol

TOL = 1e-10


@dataclass
class Targets:
    t: pd.Timestamp
    status: str                        # "ok", "ok:residual" (constraints not met exactly), "flat:<reason>"
    w_raw: pd.Series                   # baskets after inverse vol + dollar neutrality, before hedging
    w: pd.Series                       # final target (hedged, vol targeted, capped)
    exposure_raw: pd.Series            # B'w_raw per factor
    exposure: pd.Series                # B'w per factor
    short: tuple[str, ...] = ()
    long: tuple[str, ...] = ()
    signal: pd.Series = field(default_factory=pd.Series)
    vol: pd.Series = field(default_factory=pd.Series)
    betas: pd.DataFrame = field(default_factory=pd.DataFrame)


def _bars(span: str, bar: pd.Timedelta) -> int:
    return max(2, int(round(td(span) / bar)))


def _pick(ranked: pd.Index, k: int, prev, buffer_mult: float | None) -> list[str]:
    """Top k of `ranked`. With a buffer, names held last time stay while their rank is below
    buffer_mult·k; the remaining slots go to the best-ranked names not yet chosen."""
    if buffer_mult is None or not prev:
        return list(ranked[:k])
    zone = set(ranked[: int(math.floor(buffer_mult * k))])
    keep = [x for x in ranked if x in zone and x in set(prev)][:k]
    fill = [x for x in ranked if x not in set(keep)][: k - len(keep)]
    return [x for x in ranked if x in set(keep) | set(fill)]


def select_baskets(signal: pd.Series, cfg: StrategyConfig, prev_short=(), prev_long=()) -> tuple[list[str], list[str]]:
    """Short the highest carry, long the lowest. `signal` holds eligible names only.
    prev_short / prev_long: the baskets of the previous decision (used by the rank buffer).
    Returns empty lists if either side has fewer than cfg.min_names_per_side names."""
    s = signal.dropna()
    n = len(s)
    k = cfg.k if cfg.k is not None else int(math.floor(cfg.quantile * n))
    if k < 1:
        return [], []
    desc = s.sort_values(ascending=False, kind="stable")
    if cfg.short_min_signal is not None:
        desc = desc[desc > cfg.short_min_signal]
    short = _pick(desc.index, k, prev_short, cfg.buffer_mult)
    asc = s.drop(index=short).sort_values(ascending=True, kind="stable")
    if cfg.long_max_signal is not None:
        asc = asc[asc < cfg.long_max_signal]
    long = _pick(asc.index, k, prev_long, cfg.buffer_mult)
    if len(short) < cfg.min_names_per_side or len(long) < cfg.min_names_per_side:
        return [], []
    return short, long


def water_fill(raw: np.ndarray, total: float, cap: float) -> np.ndarray:
    """Split `total` in proportion to `raw` (> 0) with no element above `cap`; the excess of capped
    names goes to the others. The sum is below `total` only if every name is at the cap."""
    raw = np.asarray(raw, dtype=float)
    w = np.zeros_like(raw)
    free = raw > 0
    remaining = total
    while free.any() and remaining > TOL:
        share = remaining * raw[free] / raw[free].sum()
        over = share > cap + TOL
        if not over.any():
            w[free] = share
            break
        ids = np.flatnonzero(free)[over]
        w[ids] = cap
        remaining -= cap * len(ids)
        free[ids] = False
    return w


def basket_weights(short, long, vol: pd.Series, symbols: pd.Index, cfg: StrategyConfig) -> pd.Series:
    """Inverse-vol weights inside each basket, sides scaled to ∓ gross/2 (dollar neutral).
    If the cap prevents one side from reaching gross/2, both sides use the smaller total."""
    side = 0.5 * cfg.gross_leverage
    ws = water_fill(1.0 / vol[short].to_numpy(), side, cfg.max_weight)
    wl = water_fill(1.0 / vol[long].to_numpy(), side, cfg.max_weight)
    tot = min(ws.sum(), wl.sum())
    ws *= tot / ws.sum()
    wl *= tot / wl.sum()
    w = pd.Series(0.0, index=symbols)
    w[short] = -ws
    w[long] = wl
    return w


def neutralize(w_raw: pd.Series, betas: pd.DataFrame, targets, max_weight: float,
               keep_sign: bool = True, sign_free=(), penalty: pd.Series | None = None):
    """Closest weights to w_raw (in Σ penalty_i (w_i - w_raw_i)²) on the support betas.index with
        Σ w = 0   (dollar neutral)   and   B'w = targets   (factor exposures),
    subject to |w_i| ≤ max_weight and, if keep_sign, no basket name changing side.

    Closed form on the free set F:  w_F = w0_F - D A_F' (A_F D A_F')⁺ (A_F w0_F - b'),  D = 1/penalty.
    Names breaking a bound are fixed (at ± max_weight, or 0 for a side flip) and the projection is
    repeated. This is a one-way active set (a fixed name is never released), so with binding bounds
    the result is feasible but can be marginally farther from w_raw than the exact optimum
    (brute-force check: 4 of 300 random 6-name cases, objective gap ≤ 1e-4).
    Returns (weights on the support, max |constraint residual|).
    """
    names = betas.index
    n = len(names)
    w0 = w_raw.reindex(names).fillna(0.0).to_numpy()
    A = np.vstack([np.ones(n), betas.to_numpy(dtype=float).T])
    b = np.concatenate([[0.0], np.asarray(targets, dtype=float)])
    d = np.ones(n) if penalty is None else 1.0 / penalty.reindex(names).fillna(1.0).to_numpy()
    sgn = np.sign(w0)
    check_sign = keep_sign & (sgn != 0) & ~names.isin(list(sign_free))
    free = np.ones(n, dtype=bool)
    fixed = np.zeros(n)
    w = w0.copy()
    for _ in range(n + 1):
        w = fixed.copy()
        if free.any():
            AF = A[:, free]
            rhs = b - A[:, ~free] @ fixed[~free]
            r = AF @ w0[free] - rhs
            M = (AF * d[free]) @ AF.T
            lam = np.linalg.pinv(M) @ r
            w[free] = w0[free] - d[free] * (AF.T @ lam)
        flip = free & check_sign & (w * sgn < -TOL)
        over = free & ~flip & (np.abs(w) > max_weight + TOL)
        if not (flip.any() or over.any()):
            break
        fixed[over] = np.sign(w[over]) * max_weight
        fixed[flip] = 0.0
        free &= ~(flip | over)
    resid = float(np.abs(A @ w - b).max())
    return pd.Series(w, index=names), resid


def hedge_legs(w_raw: pd.Series, betas: pd.DataFrame, hedges: list[str], targets,
               max_weight: float) -> tuple[pd.Series, float]:
    """Keep the baskets and add hedge-leg weights h with  B_h' h = target - B'w_raw  (least squares
    if there are more hedge instruments than factors), each leg capped at ±max_weight.
    Returns (w_raw + h, max |exposure residual|). Net dollar exposure becomes Σh."""
    w = w_raw.copy()
    if hedges:
        gap = np.asarray(targets, dtype=float) - betas.loc[w.index].fillna(0.0).T.to_numpy() @ w.to_numpy()
        H = betas.loc[hedges].to_numpy(dtype=float).T             # factors × hedges
        h, *_ = np.linalg.lstsq(H, gap, rcond=None)
        w[hedges] = w[hedges].to_numpy() + np.clip(h, -max_weight, max_weight)
    exp = betas.loc[w.index].fillna(0.0).T.to_numpy() @ w.to_numpy()
    return w, float(np.abs(exp - np.asarray(targets, dtype=float)).max())


def scale_to_vol(w: pd.Series, returns: pd.DataFrame, target_vol: float, bars_per_year: float,
                 max_weight: float, gross_cap: float, min_obs: int) -> tuple[pd.Series, float]:
    """Scale w so the ex-ante vol (sample covariance of the window's bar returns) hits target_vol,
    without breaking the weight or gross caps. Scaling keeps Σw = 0 and B'w = 0. Returns (w, scale)."""
    live = w.index[w.abs() > TOL]
    if len(live) == 0:
        return w, 1.0
    cov = returns[live].cov(min_periods=min_obs).to_numpy()
    if not np.isfinite(cov).all():
        return w, 1.0
    x = w[live].to_numpy()
    vol = math.sqrt(max(float(x @ cov @ x), 0.0) * bars_per_year)
    if vol <= 0:
        return w, 1.0
    c = min(target_vol / vol, max_weight / np.abs(x).max(), gross_cap / np.abs(x).sum())
    return w * c, c


def compute_targets(snap: Snapshot, cfg: StrategyConfig, prev: "Targets | None" = None,
                    exclude=()) -> Targets:
    """prev: the previous decision (only its baskets are used, by the rank buffer).
    exclude: names that may not enter a basket now (e.g. in a stop-loss cooldown)."""
    t = snap.t
    syms = snap.close.columns
    zeros = pd.Series(0.0, index=syms)
    fz = pd.Series(0.0, index=list(cfg.factors), dtype=float)
    if snap.close.index[-1] != t:
        raise ValueError(f"decision time {t} is not a bar close in the data")
    bar, bpy = snap.bar, snap.bars_per_year
    R = snap.close.pct_change(fill_method=None)

    H = _bars(cfg.min_history, bar)
    hist_ok = snap.close.iloc[-H:].notna().sum() >= math.ceil(cfg.min_obs_frac * H)
    price_ok = snap.close.iloc[-1].notna()
    liq_ok = pd.Series(True, index=syms)
    if snap.quote_volume is not None and (cfg.min_median_quote_volume > 0 or cfg.liquidity_top_n):
        L = _bars(cfg.liquidity_window, bar)
        med = snap.quote_volume.iloc[-L:].median().where(price_ok & hist_ok)
        liq_ok = med >= cfg.min_median_quote_volume
        if cfg.liquidity_top_n:
            # hedge instruments are ranked too but never take a basket slot
            ranked = med[liq_ok & ~syms.isin(list(cfg.hedge_instruments))].sort_values(ascending=False)
            top = set(ranked.index[: cfg.liquidity_top_n]) | set(cfg.hedge_instruments)
            liq_ok = liq_ok & syms.isin(list(top))
    V = _bars(cfg.vol_window, bar)
    vmin = math.ceil(cfg.min_obs_frac * V)
    base_ok = price_ok & hist_ok & liq_ok
    vol = rolling_vol(R.iloc[-V:].loc[:, base_ok], bpy, vmin, cfg.vol_floor, cfg.vol_fallback).reindex(syms)
    signal = funding_carry(snap.funding, syms, t, td(cfg.funding_lookback), cfg.min_funding_events)
    if cfg.factors:
        Bw = _bars(cfg.beta_window, bar)
        betas = estimate_betas(R.iloc[-Bw:].loc[:, base_ok], snap.factors[list(cfg.factors)].iloc[-Bw:],
                               math.ceil(cfg.min_obs_frac * Bw), cfg.ridge, cfg.shrinkage,
                               no_shrink=cfg.hedge_instruments).reindex(syms)
        beta_ok = betas.notna().all(axis=1)
    else:
        betas = pd.DataFrame(index=syms)
        beta_ok = pd.Series(True, index=syms)
    base_ok = base_ok & vol.notna() & beta_ok
    # hedge instruments are hedge legs only: never basket names (keeps caps, sign rule and the
    # hedge PnL attribution unambiguous)
    eligible = base_ok & signal.notna() & ~syms.isin(list(cfg.hedge_instruments)) & ~syms.isin(list(exclude))

    def flat(reason):
        return Targets(t, f"flat:{reason}", zeros, zeros.copy(), fz, fz.copy(),
                       signal=signal, vol=vol, betas=betas)

    short, long = select_baskets(signal[eligible], cfg,
                                 prev.short if prev is not None else (),
                                 prev.long if prev is not None else ())
    if not short:
        return flat("baskets")
    w_raw = basket_weights(short, long, vol, syms, cfg)
    hedges = [h for h in cfg.hedge_instruments if h in syms and base_ok[h]]
    support = pd.Index(list(dict.fromkeys(short + long + hedges)))
    status = "ok"
    if cfg.factors and cfg.neutralize and cfg.neutral_mode == "hedge":
        w_s, resid = hedge_legs(w_raw[support], betas.loc[support], hedges, cfg.targets, cfg.max_weight)
        if resid > 1e-8:
            status = "ok:residual"
        w = zeros.copy()
        w[support] = w_s.to_numpy()
    elif cfg.factors and cfg.neutralize:
        pen = pd.Series(1.0, index=support)
        pen[pen.index.isin(hedges)] = cfg.hedge_penalty
        w_s, resid = neutralize(w_raw, betas.loc[support], cfg.targets, cfg.max_weight,
                                cfg.keep_sign, sign_free=hedges, penalty=pen)
        if resid > 1e-8:
            status = "ok:residual"
        w = zeros.copy()
        w[support] = w_s.to_numpy()
    else:
        w = w_raw.copy()
    if cfg.target_vol is not None:
        w, _ = scale_to_vol(w, R.iloc[-V:], cfg.target_vol, bpy, cfg.max_weight, cfg.gross_cap, vmin)
    gross = w.abs().sum()
    if gross > cfg.gross_cap:
        w = w * (cfg.gross_cap / gross)
    if w.abs().sum() <= TOL:
        return flat("zero_after_hedge")
    if cfg.factors:
        B = betas.loc[support].to_numpy()
        exp_raw = pd.Series(B.T @ w_raw[support].to_numpy(), index=list(cfg.factors))
        exp = pd.Series(B.T @ w[support].to_numpy(), index=list(cfg.factors))
    else:
        exp_raw, exp = fz, fz.copy()
    return Targets(t, status, w_raw, w, exp_raw, exp, tuple(short), tuple(long),
                   signal=signal, vol=vol, betas=betas)
