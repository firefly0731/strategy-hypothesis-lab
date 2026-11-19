"""Combinatorial Purged Cross-Validation (López de Prado, AFML ch. 12) for the
intraday momentum strategy, plus regime decomposition of the OOS returns.

Unit of observation = one session. Every trade opens and closes inside one
session, so splitting on session boundaries never cuts a trade and leaves
the strategy's intraday timeframe untouched.

  * The sessions are split into N contiguous groups, and every choice of k test groups is
    one split (C(N, k) splits). This yields C(N-1, k-1) full OOS paths.
  * purge: train sessions whose label overlaps a test session. Labels end at
    the session close, so the overlap is zero. It is kept as a parameter.
  * embargo: train sessions right AFTER a test group are dropped. Their features
    (noise sigma, daily vol) look back up to `embargo` sessions and would
    otherwise be computed from test-period prices.

Signals are causal (see signals.py), so they are computed once on the full
history. CV only decides which sessions may inform the parameter choice.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product

import numpy as np
import pandas as pd

from .backtest import Config, run_backtest
from .sessions import SessionMatrix
from .signals import compute_signals

EXEC = {
    "taker": dict(entry_mode="taker", exit_mode="taker"),
    "maker_chase": dict(entry_mode="maker", entry_fallback="taker", exit_mode="maker"),
}


@dataclass(frozen=True)
class Combo:
    lookback: int
    interval: int
    exec: str
    cost_mult: float

    @property
    def label(self) -> str:
        return f"lb{self.lookback}_iv{self.interval}_{self.exec}_cf{self.cost_mult:g}"


def default_grid() -> list[Combo]:
    return [Combo(*c) for c in product([7, 10, 14, 21, 30], [15, 30, 60],
                                       ["taker", "maker_chase"], [0.0, 2.0, 4.0, 8.0])]


def grid_session_returns(m: SessionMatrix, funding, tick: float, combos: list[Combo],
                         warmup: int = 31) -> pd.DataFrame:
    """Session returns (fraction of equity) for every combo. Rows are sessions after the
    longest warm-up, so all combos share the same index."""
    cache, cols = {}, {}
    for c in combos:
        key = (c.lookback, c.interval)
        if key not in cache:
            cache[key] = compute_signals(m, lookback=c.lookback, interval=c.interval)
        cfg = Config(tick=tick, cost_filter_mult=c.cost_mult, **EXEC[c.exec])
        r = run_backtest(m, cache[key], cfg, funding).sessions
        cols[c.label] = r["ret"].where(r["active"], 0.0).to_numpy()
    out = pd.DataFrame(cols, index=m.dates)
    return out.iloc[warmup:]


def market_session_returns(m: SessionMatrix, warmup: int = 31) -> pd.DataFrame:
    """Underlying open->close session return and its regime descriptors."""
    u = pd.Series(m.C[:, -1] / m.O[:, 0] - 1.0, index=m.dates)
    cc = pd.Series(m.C[:, -1], index=m.dates).pct_change()
    df = pd.DataFrame({
        "mkt": u,
        "abs_mkt": u.abs(),
        # ex-ante regimes: use data up to the previous session only
        "trend_60": pd.Series(m.C[:, -1], index=m.dates).pct_change(60).shift(1),
        "vol_20": cc.rolling(20).std().shift(1),
    })
    return df.iloc[warmup:]


# ----------------------------------------------------------------------------- splits

def cpcv_splits(n: int, n_groups: int = 10, k_test: int = 2, embargo: int = 30, purge: int = 0):
    groups = np.array_split(np.arange(n), n_groups)
    for test_ids in combinations(range(n_groups), k_test):
        test = np.concatenate([groups[g] for g in test_ids])
        train = np.ones(n, bool)
        train[test] = False
        for g in test_ids:
            a, b = groups[g][0], groups[g][-1]
            train[max(a - purge, 0):a] = False
            train[b + 1:b + 1 + embargo] = False
        yield test_ids, np.flatnonzero(train), test, groups


def _sharpe(x: np.ndarray, axis=0) -> np.ndarray:
    sd = x.std(axis=axis, ddof=1)
    return np.where(sd > 0, x.mean(axis=axis) / np.where(sd > 0, sd, 1), 0.0)


@dataclass
class CPCVResult:
    paths: pd.DataFrame          # (sessions, n_paths) OOS session returns
    chosen: pd.DataFrame         # per split: test groups, chosen combo, IS/OOS sharpe, rank
    pbo: float
    n_groups: int
    k_test: int


def run_cpcv(R: pd.DataFrame, n_groups: int = 10, k_test: int = 2, embargo: int = 30,
             purge: int = 0) -> CPCVResult:
    X = R.to_numpy()
    n, n_c = X.shape
    splits = list(cpcv_splits(n, n_groups, k_test, embargo, purge))
    groups = splits[0][3]
    n_paths = len(splits) * k_test // n_groups
    oos_by_group = {g: [] for g in range(n_groups)}   # list of chosen-combo returns per split
    rows = []
    for test_ids, tr, te, _ in splits:
        is_sr = _sharpe(X[tr])
        best = int(np.argmax(is_sr))
        oos_sr = _sharpe(X[te])
        rank = (oos_sr < oos_sr[best]).sum() + 0.5 * ((oos_sr == oos_sr[best]).sum() - 1) + 1
        w = rank / (n_c + 1)
        rows.append(dict(test_groups=test_ids, combo=R.columns[best],
                         is_sharpe=is_sr[best], oos_sharpe=oos_sr[best],
                         oos_rank_pct=w, logit=np.log(w / (1 - w))))
        for g in test_ids:
            oos_by_group[g].append(X[groups[g], best])
    paths = np.zeros((n, n_paths))
    for g in range(n_groups):
        assert len(oos_by_group[g]) == n_paths
        for p in range(n_paths):
            paths[groups[g], p] = oos_by_group[g][p]
    chosen = pd.DataFrame(rows)
    return CPCVResult(pd.DataFrame(paths, index=R.index), chosen,
                      float((chosen["logit"] <= 0).mean()), n_groups, k_test)


# ----------------------------------------------------------------------------- regimes

def regime_decomposition(r: pd.Series, mk: pd.DataFrame, ppy: float) -> dict:
    """r: OOS session returns. Removes market direction (beta) and shows how much
    of the return depends on ex-ante regimes."""
    d = pd.concat([r.rename("r"), mk], axis=1).dropna()
    y = d["r"].to_numpy()

    def ols(cols):
        # regressors are demeaned, so the intercept = return in an average regime
        Xm = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() - d[c].mean() for c in cols])
        b, *_ = np.linalg.lstsq(Xm, y, rcond=None)
        e = y - Xm @ b
        # Newey-West (lag 5) standard errors
        T, L = len(y), 5
        XtX_inv = np.linalg.inv(Xm.T @ Xm)
        S = (Xm * e[:, None]).T @ (Xm * e[:, None])
        for l in range(1, L + 1):
            w = 1 - l / (L + 1)
            G = (Xm[l:] * e[l:, None]).T @ (Xm[:-l] * e[:-l, None])
            S += w * (G + G.T)
        se = np.sqrt(np.diag(XtX_inv @ S @ XtX_inv))
        return b, b / se, e

    out = {"raw_mean_bps": y.mean() * 1e4, "raw_sharpe": y.mean() / y.std(ddof=1) * np.sqrt(ppy),
           "raw_t": y.mean() / y.std(ddof=1) * np.sqrt(len(y))}
    b, t, e = ols(["mkt"])
    out.update(alpha_dir_bps=b[0] * 1e4, alpha_dir_t=t[0], beta_mkt=b[1], beta_mkt_t=t[1],
               alpha_dir_sharpe=(b[0] / (e.std(ddof=1))) * np.sqrt(ppy))
    b, t, e = ols(["mkt", "trend_60", "vol_20"])
    out.update(alpha_exante_bps=b[0] * 1e4, alpha_exante_t=t[0],
               beta_trend60=b[2], beta_trend60_t=t[2], beta_vol20=b[3], beta_vol20_t=t[3])
    b, t, e = ols(["mkt", "abs_mkt"])
    out.update(alpha_absmkt_bps=b[0] * 1e4, alpha_absmkt_t=t[0], beta_absmkt=b[2], beta_absmkt_t=t[2])

    # regime-balanced mean: 2x2 ex-ante buckets (trend sign x vol above/below median)
    tr = np.where(d["trend_60"] > 0, "bull", "bear")
    vo = np.where(d["vol_20"] > d["vol_20"].median(), "hiVol", "loVol")
    cell = pd.Series(y, index=d.index).groupby([tr, vo])
    stats = pd.DataFrame({"n": cell.size(), "mean_bps": cell.mean() * 1e4,
                          "t": cell.mean() / cell.std(ddof=1) * np.sqrt(cell.size())})
    out["regime_table"] = stats
    out["regime_balanced_bps"] = stats["mean_bps"].mean()
    # contemporaneous |move| buckets (descriptive: this IS the strategy's mechanism)
    q = pd.qcut(d["abs_mkt"], 3, labels=["quiet", "normal", "trend"])
    g = pd.Series(y, index=d.index).groupby(q, observed=True)
    out["move_table"] = pd.DataFrame({"n": g.size(), "mean_bps": g.mean() * 1e4})
    return out
