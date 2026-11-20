"""Settlement-aware execution and loss limits (path-dependent, so decisions run inside the bar loop).

Execution timing (timing=True). Each rebalance targets a settlement time T on the
cfg.rebalance_every grid; 00:00 UTC is a settlement for every 1h / 4h / 8h symbol.
  * decision at T - entry_before - lag bars, from data with time ≤ that bar close;
  * increases and new entries are executed at T - entry_before bars, so they are held over the
    settlement at T (minimum holding: every position collects at least one settlement);
  * reductions and exits are executed at T, after the settlement at T has been paid.
  Between the two executions the old and new books overlap and gross can be briefly higher.

Loss limits, all checked on the bar close and executed at the NEXT bar close:
  * stop_loss: a basket name whose PnL since entry (price + funding) is at or below
    -stop_loss × equity at entry is closed with stop_slippage_bps of extra slippage, and is
    excluded from new baskets for `cooldown`. It overrides the minimum holding. Hedge legs are exempt.
  * recap_mult: a weight beyond recap_mult × max_weight is cut back to ± max_weight.
  * dd_reduce: while equity is ≥ dd_reduce below its peak, new targets are scaled by dd_reduce_scale.
  * dd_flat: at ≥ dd_flat below the peak everything is closed (stop slippage), trading pauses for
    dd_pause, and the peak resets to the equity at the restart.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import BacktestResult, funding_matrices, rebalance_times, summarize_run
from .config import StrategyConfig, td
from .data import MarketData
from .portfolio import compute_targets


@dataclass(frozen=True)
class RiskConfig:
    timing: bool = True
    entry_before_bars: int = 1
    stop_loss: float | None = 0.02
    cooldown: str = "7D"
    stop_slippage_bps: float = 20.0
    recap_mult: float | None = 1.5
    dd_reduce: float | None = 0.15
    dd_reduce_scale: float = 0.5
    dd_flat: float | None = 0.25
    dd_pause: str = "7D"

    def __post_init__(self):
        if self.entry_before_bars < 0:
            raise ValueError("entry_before_bars must be >= 0")
        if self.stop_loss is not None and self.stop_loss <= 0:
            raise ValueError("stop_loss must be > 0")
        if self.recap_mult is not None and self.recap_mult < 1:
            raise ValueError("recap_mult must be >= 1")
        if self.dd_reduce is not None and self.dd_flat is not None and self.dd_reduce >= self.dd_flat:
            raise ValueError("dd_reduce must be below dd_flat")
        if not 0 < self.dd_reduce_scale <= 1 or self.stop_slippage_bps < 0:
            raise ValueError("need 0 < dd_reduce_scale <= 1 and stop_slippage_bps >= 0")

    @classmethod
    def off(cls, timing: bool = False) -> "RiskConfig":
        return cls(timing=timing, stop_loss=None, recap_mult=None, dd_reduce=None, dd_flat=None)


def run_managed(data: MarketData, cfg: StrategyConfig, risk: RiskConfig, use: str = "hedged",
                initial_equity: float = 1.0, exit_up: np.ndarray | None = None,
                exit_down: np.ndarray | None = None) -> BacktestResult:
    """exit_up / exit_down: optional (bars × symbols) booleans, True where an upside / downside
    breakout became known by that bar's close (momentum_exit.to_bar_grid). A short basket name
    with exit_up, or a long one with exit_down, is closed on the next bar (stop slippage) and may
    not re-enter before the next decision. Hedge legs are exempt."""
    idx, syms = data.close.index, data.symbols
    N, S = len(idx), len(syms)
    C = data.close.to_numpy(dtype=float)
    fin = np.isfinite(C)
    last_valid = np.where(fin.any(axis=0), N - 1 - np.argmax(fin[::-1], axis=0), -1)
    fe, fi = funding_matrices(data)
    hedge = syms.isin(list(cfg.hedge_instruments))
    rate = cfg.costs.rate
    stop_rate = rate + risk.stop_slippage_bps * 1e-4
    lag = cfg.exec_lag_bars
    eb = risk.entry_before_bars if risk.timing else 0
    e = td(cfg.rebalance_every)
    if e % data.bar != pd.Timedelta(0) or td(cfg.rebalance_offset) % data.bar != pd.Timedelta(0):
        raise ValueError("rebalance_every and rebalance_offset must be multiples of the bar length")

    # decision bar -> (increase bar, full bar)
    first_ok = idx[0] + cfg.lookback
    plan = {}
    for jT in idx.get_indexer(rebalance_times(idx, cfg.rebalance_every, cfg.rebalance_offset)):
        jd = jT - eb - lag if risk.timing else jT
        if jd < 0 or idx[jd] < first_ok:
            continue
        j_full = jT if risk.timing else jT + lag
        if j_full < N:
            plan[jd] = (j_full - eb if risk.timing else j_full, j_full)

    n = np.zeros(S)
    E = float(initial_equity)
    last = C[0].copy()
    peak = E
    paused_until = None
    cool_until = np.full(S, np.iinfo(np.int64).min)
    entry_E = np.zeros(S)
    cum = np.zeros(S)
    inc_orders, full_orders, risk_orders = {}, {}, {}
    schedule, prev_tg, first_exec = [], None, None
    cols = ("equity", "price_pnl", "hedge_price_pnl", "funding_pnl", "cost", "turnover", "gross", "net",
            "untraded", "stops", "recaps", "flatten", "scale", "paused", "mom_exits")
    dec_bars = np.array(sorted(plan))
    for name, arr in (("exit_up", exit_up), ("exit_down", exit_down)):
        if arr is not None and arr.shape != (N, S):
            raise ValueError(f"{name} must have shape (bars, symbols)")
    rec = np.zeros((N, len(cols)))
    held = np.zeros((N, S))
    ruined = False
    scale = 1.0
    t_ns = idx.as_unit("ns").asi8

    for j in range(N):
        pp = hp = pf = cst = to = unt = 0.0
        ev_stop = ev_recap = ev_flat = ev_mom = 0
        ok = fin[j]
        if j > 0 and not ruined:
            p = C[j]
            r = np.zeros(S)
            v = ok & np.isfinite(last)
            r[v] = p[v] / last[v] - 1.0
            n_pre = n
            pnl = n_pre * r
            n = n_pre * (1.0 + r)
            fund = -(n_pre * fi[j] + n * fe[j])
            pp, hp, pf = pnl.sum(), pnl[hedge].sum(), fund.sum()
            cum += pnl + fund
            E += pp + pf
            dead = ~ok & (j > last_valid) & (n != 0)
            if dead.any():
                traded = np.abs(n[dead]).sum()
                c = traded * rate
                to += 0.5 * traded / E if E > 0 else 0.0
                n = n.copy()
                n[dead] = 0.0
                E -= c
                cst += c
            last = np.where(ok, p, last)
        paused = paused_until is not None and t_ns[j] < paused_until
        n_before = n.copy()

        def trade(w_new, r_cost):
            nonlocal n, E, cst, to, unt
            stuck = ~ok
            unt += np.abs(w_new[stuck] - n[stuck] / E).sum()
            w_new = w_new.copy()
            w_new[stuck] = n[stuck] / E
            dw = w_new - n / E
            if not np.abs(dw).sum():
                return
            c = np.abs(dw).sum() * E * r_cost
            E -= c
            n_new = w_new * E
            same = dw == 0
            n_new[same] = n[same]
            n = n_new
            cst += c
            to += 0.5 * np.abs(dw).sum()

        if not ruined and E > 0:
            if j in risk_orders:                                   # stops / recaps / flatten
                for ids, vals, r_cost in risk_orders.pop(j):
                    w = n / E
                    w[ids] = vals
                    trade(w, r_cost)
            cooled = cool_until > t_ns[j]
            if j in inc_orders:
                w_t = inc_orders.pop(j)
                if not paused:
                    w_cur = n / E
                    grow = (w_t * w_cur > 0) & (np.abs(w_t) > np.abs(w_cur))
                    new = (w_cur == 0) & (w_t != 0) & ~cooled
                    trade(np.where(grow & ~cooled | new, w_t, w_cur), rate)
                    first_exec = first_exec if first_exec is not None else idx[j]
            if j in full_orders:
                w_t = full_orders.pop(j)
                if not paused:
                    w_t = np.where(cooled, 0.0, w_t)
                    trade(w_t, rate)
                    first_exec = first_exec if first_exec is not None else idx[j]
        # entry bookkeeping after this bar's trades
        opened = ((n_before == 0) & (n != 0)) | (n_before * n < 0)
        entry_E[opened] = E
        cum[opened] = 0.0
        cum[n == 0] = 0.0

        # --- loss limits, decided on this close, executed next bar
        if E <= 0 and not ruined:
            ruined, n = True, np.zeros(S)
        if not ruined and j + 1 < N:
            peak = max(peak, E)
            if paused_until is not None and t_ns[j] >= paused_until:
                paused_until, peak = None, E
            if (risk.dd_flat is not None and paused_until is None and E <= peak * (1 - risk.dd_flat)
                    and np.abs(n).sum() > 0):
                risk_orders.setdefault(j + 1, []).append((np.arange(S), 0.0, stop_rate))
                paused_until = t_ns[j] + td(risk.dd_pause).value
                ev_flat = 1
            elif paused_until is None:
                w = n / E
                stop_ids = np.array([], dtype=int)
                if risk.stop_loss is not None:
                    hit = (n != 0) & ~hedge & (cum <= -risk.stop_loss * entry_E)
                    stop_ids = np.flatnonzero(hit)
                    if len(stop_ids):
                        risk_orders.setdefault(j + 1, []).append((stop_ids, 0.0, stop_rate))
                        cool_until[stop_ids] = t_ns[j] + td(risk.cooldown).value
                        ev_stop = len(stop_ids)
                if exit_up is not None or exit_down is not None:
                    against = np.zeros(S, dtype=bool)
                    if exit_up is not None:
                        against |= (n < 0) & exit_up[j]
                    if exit_down is not None:
                        against |= (n > 0) & exit_down[j]
                    against &= ~hedge
                    against[stop_ids] = False
                    mom_ids = np.flatnonzero(against)
                    if len(mom_ids):
                        risk_orders.setdefault(j + 1, []).append((mom_ids, 0.0, stop_rate))
                        nxt = dec_bars[dec_bars > j]
                        until = t_ns[nxt[0]] if len(nxt) else np.iinfo(np.int64).max
                        cool_until[mom_ids] = np.maximum(cool_until[mom_ids], until)
                        stop_ids = np.concatenate([stop_ids, mom_ids])
                        ev_mom = len(mom_ids)
                if risk.recap_mult is not None:
                    big = np.abs(w) > risk.recap_mult * cfg.max_weight
                    big[stop_ids] = False
                    ids = np.flatnonzero(big)
                    if len(ids):
                        risk_orders.setdefault(j + 1, []).append((ids, np.sign(w[ids]) * cfg.max_weight, rate))
                        ev_recap = len(ids)
            dd = 1 - E / peak if peak > 0 else 0.0
            scale = risk.dd_reduce_scale if (risk.dd_reduce is not None and dd >= risk.dd_reduce) else 1.0

        # --- decision
        paused = paused_until is not None and t_ns[j] < paused_until
        if j in plan and not ruined and not paused:
            snap = data.snapshot(idx[j], cfg.lookback, cfg.funding_history)
            tg = compute_targets(snap, cfg, prev_tg, exclude=list(syms[cool_until > t_ns[j]]))
            schedule.append(tg)
            prev_tg = tg
            w = (tg.w if use == "hedged" else tg.w_raw).reindex(syms).fillna(0.0).to_numpy() * scale
            j_inc, j_full = plan[j]
            if j_inc != j_full:
                inc_orders[j_inc] = w
            full_orders[j_full] = w

        rec[j] = (E, pp, hp, pf, cst, to, np.abs(n).sum() / E if E > 0 else 0.0,
                  n.sum() / E if E > 0 else 0.0, unt, ev_stop, ev_recap, ev_flat, scale, float(paused), ev_mom)
        held[j] = n / E if E > 0 else 0.0

    bars = pd.DataFrame(rec, index=idx, columns=cols)
    bars["ret"] = bars["equity"].pct_change().fillna(0.0)
    weights = pd.DataFrame(held, index=idx, columns=syms)
    res = summarize_run(data, cfg, bars, weights, schedule, first_exec)
    res.metrics.update(n_stops=int(bars["stops"].sum()), n_recaps=int(bars["recaps"].sum()),
                       n_flatten=int(bars["flatten"].sum()), n_mom_exits=int(bars["mom_exits"].sum()),
                       share_reduced=float((bars["scale"] < 1).mean()), share_paused=float(bars["paused"].mean()))
    return res
