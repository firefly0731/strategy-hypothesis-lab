"""Decision schedule, bar-by-bar simulation, PnL attribution and performance statistics.

Order of events inside bar j (interval (t_{j-1}, t_j]):
  1. price move: notional n_i drifts with the bar return (price PnL)
  2. funding: each settlement s in the bar pays -n_i(s) × rate. n_i(s) is the drifted notional
     when s == t_j, and the bar-start notional when s is strictly inside the bar (exact when
     settlements fall on bar closes, e.g. hourly bars).
  3. a held name with no price at t_j: if it trades again later (outage) the position is held and
     its return is booked when the price returns; if it never trades again (delisting / data end)
     it is closed at its last price, with costs
     (whether a later price exists is known to the exchange, not to the strategy: decisions never
     see it, it only decides when the venue settles a delisted contract)
  4. decision at t_j if it is on the rebalance grid: targets from data with time ≤ t_j only
  5. execution of the order decided lag bars earlier, at close t_j:
     traded = Σ|w_target - w_drift| × equity, cost = traded × (fee + slippage),
     one-way turnover = 0.5 × Σ|w_target - w_drift|; positions are set to w_target × post-cost
     equity. A name without a price at execution keeps its position (column `untraded` = the
     weight that could not be traded).
Equity is tracked in money, so price + funding - cost adds up exactly to the change in equity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import CostConfig, StrategyConfig, td
from .data import YEAR, MarketData
from .portfolio import Targets, compute_targets


def rebalance_times(index: pd.DatetimeIndex, every: str, offset: str = "0h") -> pd.DatetimeIndex:
    e, o = td(every), td(offset)
    ns = index.as_unit("ns").asi8
    return index[(ns - o.value) % e.value == 0]


def compute_schedule(data: MarketData, cfg: StrategyConfig) -> list[Targets]:
    """Targets at every rebalance time, each computed from a snapshot that ends at that time."""
    e = td(cfg.rebalance_every)
    if e % data.bar != pd.Timedelta(0) or td(cfg.rebalance_offset) % data.bar != pd.Timedelta(0):
        raise ValueError("rebalance_every and rebalance_offset must be multiples of the bar length")
    out = []
    first_ok = data.close.index[0] + cfg.lookback
    for t in rebalance_times(data.close.index, cfg.rebalance_every, cfg.rebalance_offset):
        if t < first_ok:
            continue
        snap = data.snapshot(t, cfg.lookback, cfg.funding_history)
        out.append(compute_targets(snap, cfg, out[-1] if out else None))
    return out


def orders_from_schedule(data: MarketData, schedule: list[Targets], lag: int, use: str = "hedged") -> pd.DataFrame:
    """Target weights indexed by execution time (decision time + lag bars)."""
    if use not in ("hedged", "raw"):
        raise ValueError("use must be 'hedged' or 'raw'")
    idx = data.close.index
    rows, times = [], []
    for tg in schedule:
        j = idx.get_loc(tg.t) + lag
        if j >= len(idx):
            continue
        rows.append((tg.w if use == "hedged" else tg.w_raw).reindex(data.symbols).fillna(0.0))
        times.append(idx[j])
    if not rows:
        return pd.DataFrame(columns=data.symbols, index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(times)).astype(float)


def funding_matrices(data: MarketData) -> tuple[np.ndarray, np.ndarray]:
    """(at_close, inside) rate matrices, bars × symbols: summed settled rates that fall exactly on
    the bar close t_j, and strictly inside (t_{j-1}, t_j). Settlements at or before the first bar
    close, or after the last, are dropped (no position can be held over them)."""
    idx = data.close.index
    N, S = len(idx), len(data.symbols)
    at_close, inside = np.zeros((N, S)), np.zeros((N, S))
    f = data.funding
    if f.empty:
        return at_close, inside
    times = pd.DatetimeIndex(f["time"])
    j = idx.searchsorted(times, side="left")
    keep = (j > 0) & (j < N)
    col = data.symbols.get_indexer(f["symbol"])
    rate = f["rate"].to_numpy(dtype=float)
    on = np.zeros(len(f), dtype=bool)
    on[keep] = idx[j[keep]] == times[keep]
    np.add.at(at_close, (j[keep & on], col[keep & on]), rate[keep & on])
    np.add.at(inside, (j[keep & ~on], col[keep & ~on]), rate[keep & ~on])
    return at_close, inside


def simulate(data: MarketData, orders: pd.DataFrame, costs: CostConfig,
             hedge_symbols=(), initial_equity: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the bar loop for the given target weights (index = execution times).
    Returns (bars, weights): per-bar accounting and the weights held at each bar close."""
    idx, syms = data.close.index, data.symbols
    N, S = len(idx), len(syms)
    C = data.close.to_numpy(dtype=float)
    fe, fi = funding_matrices(data)
    W = orders.reindex(columns=syms).fillna(0.0).to_numpy(dtype=float)
    pos = idx.get_indexer(orders.index)
    if (pos < 0).any():
        raise ValueError("order times must be bar closes of the data")
    order_at = {int(p): i for i, p in enumerate(pos)}
    hedge = syms.isin(list(hedge_symbols))
    rate = costs.rate

    n = np.zeros(S)
    E = float(initial_equity)
    last = C[0].copy()
    fin = np.isfinite(C)
    # last bar with a price: after it the contract is gone (delisting / data end)
    last_valid = np.where(fin.any(axis=0), N - 1 - np.argmax(fin[::-1], axis=0), -1)
    cols = ("equity", "price_pnl", "hedge_price_pnl", "funding_pnl", "cost", "turnover", "gross",
            "net", "untraded")
    rec = np.zeros((N, len(cols)))
    held = np.zeros((N, S))
    ruined = False
    for j in range(N):
        pp = hp = pf = cst = to = unt = 0.0
        ok = fin[j]
        if j > 0 and not ruined:
            p = C[j]
            r = np.zeros(S)
            v = ok & np.isfinite(last)
            r[v] = p[v] / last[v] - 1.0          # across a data gap: return since the last price
            n_pre = n
            pnl = n_pre * r
            pp, hp = pnl.sum(), pnl[hedge].sum()
            n = n_pre * (1.0 + r)
            pf = -(n_pre @ fi[j] + n @ fe[j])
            E += pp + pf
            # a gap with a later price is an outage: hold. No later price: closed at the last price.
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
        if j in order_at and not ruined and E > 0:
            w_t = W[order_at[j]].copy()
            stuck = ~ok                              # no price now: cannot trade, keep the position
            unt = np.abs(w_t[stuck] - n[stuck] / E).sum()
            w_t[stuck] = n[stuck] / E
            dw = w_t - n / E
            c = np.abs(dw).sum() * E * rate
            E -= c
            n_new = w_t * E                          # target weights of post-cost equity
            same = dw == 0                           # untraded names keep their notional exactly
            n_new[same] = n[same]
            n = n_new
            cst += c
            to += 0.5 * np.abs(dw).sum()
        if E <= 0 and not ruined:
            ruined, n = True, np.zeros(S)
        rec[j] = (E, pp, hp, pf, cst, to, np.abs(n).sum() / E if E > 0 else 0.0,
                  n.sum() / E if E > 0 else 0.0, unt)
        held[j] = n / E if E > 0 else 0.0
    bars = pd.DataFrame(rec, index=idx, columns=cols)
    bars["ret"] = bars["equity"].pct_change().fillna(0.0)
    return bars, pd.DataFrame(held, index=idx, columns=syms)


# ---------------------------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------------------------
def performance(equity: pd.Series, bars_per_year: float) -> dict:
    """Headline statistics. Sharpe is computed twice (bar returns and daily returns,
    RESEARCH_PROTOCOL.md §4); a large gap between the two needs investigating."""
    r = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]) / YEAR
    growth = equity.iloc[-1] / equity.iloc[0]
    cagr = growth ** (1 / years) - 1 if years > 0 and growth > 0 else np.nan
    sd = r.std(ddof=1)
    downside = np.sqrt((np.minimum(r, 0.0) ** 2).mean())
    dd = equity / equity.cummax() - 1
    mdd = dd.min()
    eod = equity.resample("1D", label="right", closed="right").last().dropna()
    if eod.index[0] > equity.index[0]:                 # keep the first (partial) day's return
        eod = pd.concat([equity.iloc[:1], eod])
    daily = eod.pct_change().dropna()
    return dict(
        total_return=growth - 1,
        cagr=cagr,
        vol=sd * np.sqrt(bars_per_year),
        sharpe=r.mean() / sd * np.sqrt(bars_per_year) if sd > 0 else np.nan,
        sharpe_daily=daily.mean() / daily.std(ddof=1) * np.sqrt(365) if len(daily) > 2 and daily.std() > 0 else np.nan,
        sortino=r.mean() * bars_per_year / (downside * np.sqrt(bars_per_year)) if downside > 0 else np.nan,
        mdd=mdd,
        calmar=cagr / -mdd if mdd < 0 else np.nan,
        years=years,
        n_bars=len(r),
    )


def realized_betas(ret: pd.Series, factors: pd.DataFrame, freq: str = "1D") -> pd.DataFrame:
    """Ex-post OLS betas of strategy returns on factor returns, both compounded to `freq`.
    One univariate regression per factor plus a joint one. Columns: beta, t, r2, n."""
    def comp(x):
        return (1 + x).resample(freq, label="right", closed="right").prod(min_count=1) - 1
    y_all = comp(ret)
    F_all = factors.apply(comp)
    rows = {}

    def ols(y, X):
        X1 = np.column_stack([np.ones(len(y)), X])
        coef, *_ = np.linalg.lstsq(X1, y, rcond=None)
        e = y - X1 @ coef
        dof = len(y) - X1.shape[1]
        s2 = e @ e / dof
        se = np.sqrt(np.diag(s2 * np.linalg.pinv(X1.T @ X1)))
        r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean())) if y.std() > 0 else np.nan
        with np.errstate(divide="ignore", invalid="ignore"):
            tt = np.where(se[1:] > 0, coef[1:] / se[1:], np.nan)
        return coef[1:], tt, r2

    for f in factors.columns:
        m = y_all.notna() & F_all[f].notna()
        if m.sum() < 10:
            continue
        b, tt, r2 = ols(y_all[m].to_numpy(), F_all.loc[m, [f]].to_numpy())
        rows[f] = dict(beta=b[0], t=tt[0], r2=r2, n=int(m.sum()))
    if factors.shape[1] > 1:
        m = y_all.notna() & F_all.notna().all(axis=1)
        if m.sum() >= 10:
            b, tt, r2 = ols(y_all[m].to_numpy(), F_all[m].to_numpy())
            for i, f in enumerate(factors.columns):
                rows[f"{f} (joint)"] = dict(beta=b[i], t=tt[i], r2=r2, n=int(m.sum()))
    return pd.DataFrame(rows).T


def exposure_report(schedule: list[Targets], factors) -> pd.DataFrame:
    """Per decision: factor exposure before (raw) and after (hedged) neutralisation, net/gross."""
    rows = []
    for tg in schedule:
        row = dict(t=tg.t, status=tg.status, n_short=len(tg.short), n_long=len(tg.long),
                   net_raw=tg.w_raw.sum(), net=tg.w.sum(),
                   gross_raw=tg.w_raw.abs().sum(), gross=tg.w.abs().sum())
        for f in factors:
            row[f"{f}_raw"] = tg.exposure_raw.get(f, np.nan)
            row[f"{f}_hedged"] = tg.exposure.get(f, np.nan)
        rows.append(row)
    return pd.DataFrame(rows).set_index("t") if rows else pd.DataFrame()


@dataclass
class BacktestResult:
    bars: pd.DataFrame
    weights: pd.DataFrame
    schedule: list[Targets]
    exposures: pd.DataFrame
    metrics: dict
    attribution: dict
    betas: pd.DataFrame
    orders: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_backtest(data: MarketData, cfg: StrategyConfig, use: str = "hedged",
                 initial_equity: float = 1.0, schedule: list[Targets] | None = None) -> BacktestResult:
    """use="hedged" trades the factor-neutral targets, use="raw" the dollar-neutral baskets only
    (the same schedule, for a like-for-like comparison of factor exposure)."""
    if schedule is None:
        schedule = compute_schedule(data, cfg)
    orders = orders_from_schedule(data, schedule, cfg.exec_lag_bars, use)
    bars, weights = simulate(data, orders, cfg.costs, cfg.hedge_instruments, initial_equity)
    first = orders.index[0] if len(orders) else None
    return summarize_run(data, cfg, bars, weights, schedule, first, orders)


def summarize_run(data: MarketData, cfg: StrategyConfig, bars: pd.DataFrame, weights: pd.DataFrame,
                  schedule: list[Targets], first_exec, orders: pd.DataFrame | None = None) -> BacktestResult:
    """Metrics, attribution, exposure report and ex-post betas from the first execution onwards."""
    orders = pd.DataFrame() if orders is None else orders
    live = bars.index >= first_exec if first_exec is not None else np.zeros(len(bars), dtype=bool)
    # metrics start at the bar before the first execution (equity before any trade)
    if live.any():
        start = max(0, int(np.argmax(live)) - 1)
        eq = bars["equity"].iloc[start:]
        metrics = performance(eq, data.bars_per_year)
        period = bars.iloc[start + 1:]
    else:
        metrics, period = {}, bars.iloc[0:0]
    rebal = period.loc[period["turnover"] > 0, "turnover"]
    years = metrics.get("years", np.nan)
    metrics.update(
        turnover_per_rebalance=rebal.mean() if len(rebal) else 0.0,
        turnover_annual=period["turnover"].sum() / years if years and years > 0 else np.nan,
        avg_gross=period["gross"].mean() if len(period) else np.nan,
        avg_abs_net=period["net"].abs().mean() if len(period) else np.nan,
        n_decisions=len(schedule),
        n_flat=sum(tg.status.startswith("flat") for tg in schedule),
        n_residual=sum(tg.status == "ok:residual" for tg in schedule),
        n_untraded=int((period["untraded"] > 0).sum()),
    )
    attribution = dict(
        funding_pnl=period["funding_pnl"].sum(),
        price_pnl=period["price_pnl"].sum(),
        price_pnl_baskets=period["price_pnl"].sum() - period["hedge_price_pnl"].sum(),
        price_pnl_hedge=period["hedge_price_pnl"].sum(),
        trading_cost=-period["cost"].sum(),
    )
    attribution["total"] = attribution["funding_pnl"] + attribution["price_pnl"] + attribution["trading_cost"]
    attribution["equity_change"] = (bars["equity"].iloc[-1] - bars["equity"].iloc[max(0, int(np.argmax(live)) - 1)]
                                    if live.any() else 0.0)
    exposures = exposure_report(schedule, cfg.factors)
    if cfg.factors and live.any():
        betas = realized_betas(period["ret"], data.factors.loc[period.index, list(cfg.factors)])
    else:
        betas = pd.DataFrame()
    return BacktestResult(bars, weights, schedule, exposures, metrics, attribution, betas, orders)
