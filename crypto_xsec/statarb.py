"""Avellaneda & Lee (2010) residual statistical arbitrage, replicated on crypto perps.

Faithful rules (paper section 4 + appendix):
  * the 60-day regression R_i = b0 + beta * F + eps (F = factor return)
  * X_k = cumsum(eps), AR(1) X_{n+1} = a + b X_n + zeta
  * reject the name unless 0 < b < exp(-1/30) (kappa > year/30, i.e. tau < 30 days)
  * s = -m_c / sigma_eq with m = a/(1-b) centred across names, sigma_eq = sqrt(var(zeta)/(1-b^2))
  * bang-bang: open long s < -1.25, open short s > 1.25, close short s < 0.75, close long s > -0.50
  * market-neutral legs: +$Q coin, -$Q*beta factor; cost 5 bp per unit of turnover

Timing (look-ahead safe):
  * signal day d = UTC [00:00 d, 00:00 d+1); the signal uses returns up to the close of day d
  * orders execute 30 minutes later (00:30 d+1), and P&L for day d+1 is the 00:30 -> 00:30 return
  * eligibility (history, liquidity) and PCA weights use data up to day d only

Factors: "btc" (BTC as the single market factor, BTC itself not traded) or "pca1"
(first eigenportfolio of the trailing correlation matrix, weights v_i / sigma_i).

    python -m crypto_xsec.statarb
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from crypto_intraday_momentum.data import load_funding
from crypto_intraday_momentum.sizing import metrics
from .panel import build_panel

YEAR = 365


@dataclass(frozen=True)
class Params:
    window: int = 60
    s_bo: float = 1.25          # buy to open  if s < -s_bo
    s_so: float = 1.25          # sell to open if s > +s_so
    s_bc: float = 0.75          # close short  if s < +s_bc
    s_sc: float = 0.50          # close long   if s > -s_sc
    tau_max: float = 30.0       # days
    factor: str = "btc"         # btc | pca1
    pca_window: int = 120
    cost_bps: float = 5.0       # per unit of turnover (paper: 5 bp)
    min_hist: int = 90
    min_qv: float = 20e6        # trailing 30d median daily quote volume, USD
    funding: bool = True
    vol_condition: str = "none" # none | high_only | scale  (Nagel 2012)


def daily_panels(P: pd.DataFrame):
    """Signal returns (00:00->00:00) and P&L returns (00:30->00:30), both indexed by UTC day."""
    r = P["r"]
    day_sig = r.index.floor("D")
    sig = r.groupby(day_sig).sum(min_count=48)
    sig[r.isna().groupby(day_sig).sum() > 0] = np.nan
    shifted = r.copy()
    shifted.index = shifted.index - pd.Timedelta(minutes=30)     # 00:30 -> 00:00 bucket
    day_pnl = shifted.index.floor("D")
    pnl = shifted.groupby(day_pnl).sum(min_count=48)
    pnl[shifted.isna().groupby(day_pnl).sum() > 0] = np.nan
    qv = P["qv"].groupby(day_sig).sum()
    for x in (sig, pnl, qv):
        x.index = x.index.tz_convert(None)
    # align on the signal-day index: row d of every panel refers to the same UTC day
    pnl = pnl.reindex(sig.index)
    qv = qv.reindex(sig.index)
    return np.exp(sig) - 1, np.exp(pnl) - 1, qv


def daily_funding(symbols, start, end, index) -> pd.DataFrame:
    """Sum of funding rates settled in (00:30 d, 00:30 d+1], booked on day d (P&L day)."""
    out = {}
    for s in symbols:
        f = load_funding(s, start, end)
        if f.empty:
            continue
        t = pd.DatetimeIndex(f["time"]).tz_convert(None) - pd.Timedelta(minutes=30)
        out[s] = pd.Series(f["rate"].to_numpy(), index=t).groupby(t.floor("D")).sum()
    return pd.DataFrame(out).reindex(index).fillna(0.0)


def _ou_scores(Y: np.ndarray, F: np.ndarray, p: Params):
    """Y: (window, n) coin returns, F: (window,) factor. Returns beta, s (centred), valid mask."""
    W, n = Y.shape
    Fm = F - F.mean()
    Ym = Y - Y.mean(0)
    beta = (Fm[:, None] * Ym).sum(0) / (Fm ** 2).sum()
    b0 = Y.mean(0) - beta * F.mean()
    eps = Y - b0 - beta * F[:, None]
    X = np.cumsum(eps, axis=0)
    x0, x1 = X[:-1], X[1:]
    x0m = x0 - x0.mean(0)
    b = (x0m * (x1 - x1.mean(0))).sum(0) / (x0m ** 2).sum(0)
    a = x1.mean(0) - b * x0.mean(0)
    zeta = x1 - a - b * x0
    var_z = zeta.var(0, ddof=1)
    valid = (b > 0) & (b < np.exp(-1.0 / p.tau_max))
    m = np.where(valid, a / (1 - b), np.nan)
    m_c = m - np.nanmean(m) if valid.any() else m
    sig_eq = np.sqrt(var_z / (1 - b ** 2))
    s = np.where(valid, -m_c / sig_eq, np.nan)
    return beta, s, valid


def run(Rs: pd.DataFrame, Rp: pd.DataFrame, QV: pd.DataFrame, FUND: pd.DataFrame, p: Params,
        btc="BTCUSDT"):
    days = Rs.index
    syms = list(Rs.columns)
    for name, X in (("Rp", Rp), ("QV", QV), ("FUND", FUND)):
        if not X.index.equals(days):
            raise ValueError(f"{name} is not aligned with the signal-day index")
    Rs_a, Rp_a = Rs.to_numpy(), Rp.to_numpy()
    hist = np.cumsum(np.isfinite(Rs_a), axis=0)
    qv_med = QV.rolling(30, min_periods=20).median().to_numpy()
    fund = FUND.reindex(columns=syms).fillna(0.0).to_numpy()
    ib = syms.index(btc)
    # market realised vol for the Nagel condition (BTC, 20d), and its trailing 1y median
    rv = pd.Series(Rs_a[:, ib]).rolling(20, min_periods=15).std()
    rv_med = rv.rolling(365, min_periods=120).median()
    pos = np.zeros(len(syms))            # +1 long / -1 short / 0 (state of each coin)
    Q = np.zeros(len(syms))              # dollar exposure of each coin leg (fraction of equity)
    hedge_w = np.zeros(len(syms))        # factor exposure per coin leg (fraction of equity)
    prev_beta = np.zeros(len(syms))
    rows = []
    W = p.window
    for d in range(W, len(days) - 1):
        win = slice(d - W + 1, d + 1)
        elig = (hist[d] >= max(p.min_hist, W)) & (qv_med[d] >= p.min_qv) & np.isfinite(Rs_a[win]).all(0)
        if p.factor == "btc":
            elig[ib] = False
            if not np.isfinite(Rs_a[win, ib]).all():
                elig[:] = False
        idx = np.flatnonzero(elig)
        s_all = np.full(len(syms), np.nan)
        beta_all = np.zeros(len(syms))
        fw = None
        if len(idx) >= 5:
            if p.factor == "btc":
                F = Rs_a[win, ib]
            else:                          # PCA1 eigenportfolio on trailing correlation
                pw = slice(max(0, d - p.pca_window + 1), d + 1)   # never wraps around
                Z = Rs_a[pw][:, idx]
                okc = np.isfinite(Z).all(0)
                Z = Z[:, okc]
                sd = Z.std(0, ddof=1)
                F = None
                if Z.shape[0] >= 60 and okc.sum() >= 5 and (sd > 0).all():
                    C = np.corrcoef((Z - Z.mean(0)) / sd, rowvar=False)
                    v = np.linalg.eigh(C)[1][:, -1]
                    v = v * np.sign(v.sum())
                    w = v / sd
                    fw = np.zeros(len(syms)); fw[idx[okc]] = w / np.abs(w).sum()
                    F = np.nan_to_num(Rs_a[win]) @ fw
            if F is not None:
                beta, s, valid = _ou_scores(Rs_a[win][:, idx], F, p)
                s_all[idx] = s
                beta_all[idx] = beta
        # state machine (paper rules); a rejected/ineligible name is closed
        new = pos.copy()
        for k in range(len(syms)):
            sk = s_all[k]
            if not np.isfinite(sk):
                new[k] = 0
            elif pos[k] == 0:
                new[k] = 1 if sk < -p.s_bo else (-1 if sk > p.s_so else 0)
            elif pos[k] == 1 and sk > -p.s_sc:
                new[k] = 0
            elif pos[k] == -1 and sk < p.s_bc:
                new[k] = 0
        n_el = max(len(idx), 1)
        lam = 1.0 / n_el                   # equal $ per position, ~ "1+1" when all names active
        if p.vol_condition != "none":
            ratio = rv.iloc[d] / rv_med.iloc[d] if np.isfinite(rv_med.iloc[d]) else np.nan
            if p.vol_condition == "high_only":
                lam = lam if (np.isfinite(ratio) and ratio > 1) else 0.0
            elif p.vol_condition == "scale":
                lam = lam * (np.clip(ratio, 0.5, 2.0) if np.isfinite(ratio) else 1.0)
        # paper: the sizing factor is applied to NEW positions only; held positions keep their size
        keep = (new == pos) & (new != 0)
        Q_new = np.where(keep, Q, new * lam)
        hedge_new = -Q_new * beta_all        # factor exposure from each leg
        # turnover: coin legs + net factor position change
        if p.factor == "btc":
            fac_old, fac_new = hedge_w.sum(), hedge_new.sum()
            turn = np.abs(Q_new - Q).sum() + abs(fac_new - fac_old)
        else:
            fac_old = hedge_w.sum() * (fw if fw is not None else 0)
            fac_new = hedge_new.sum() * (fw if fw is not None else 0)
            turn = np.abs(Q_new - Q).sum() + np.abs(np.asarray(fac_new) - np.asarray(fac_old)).sum()
        cost = turn * p.cost_bps * 1e-4
        # P&L over the next P&L day (00:30 d+1 -> 00:30 d+2)
        rp = np.nan_to_num(Rp_a[d + 1])
        if p.factor == "btc":
            f_ret = rp[ib]
            f_fund = fund[d + 1, ib]
        else:
            f_ret = rp @ fw if fw is not None else 0.0
            f_fund = fund[d + 1] @ fw if fw is not None else 0.0
        gross = (Q_new * rp).sum() + hedge_new.sum() * f_ret
        fnd = ((Q_new * fund[d + 1]).sum() + hedge_new.sum() * f_fund) if p.funding else 0.0
        rows.append((days[d + 1], gross, cost, fnd, gross - cost - fnd, (new != 0).sum(), len(idx),
                     np.abs(Q_new).sum() + abs(hedge_new.sum())))
        pos, Q, hedge_w, prev_beta = new, Q_new, hedge_new, beta_all
    return pd.DataFrame(rows, columns=["date", "gross", "cost", "funding", "net", "n_pos", "n_elig",
                                       "gross_lev"]).set_index("date")


def summarize(res: pd.DataFrame, ppy=YEAR) -> dict:
    r = res["net"]
    mt = metrics(r, ppy)
    return dict(sharpe=mt["sharpe"], t=mt["t"], cagr=mt["cagr"], mdd=mt["mdd"], vol=mt["vol"],
                gross_bps_day=res["gross"].mean() * 1e4, cost_bps_day=res["cost"].mean() * 1e4,
                funding_bps_day=res["funding"].mean() * 1e4, avg_pos=res["n_pos"].mean(),
                avg_elig=res["n_elig"].mean(), avg_gross_lev=res["gross_lev"].mean())


def load_inputs(start="2021-01", end="2026-10"):
    P = build_panel()
    Rs, Rp, QV = daily_panels(P)
    FUND = daily_funding(list(Rs.columns), start, end, Rs.index)
    return Rs, Rp, QV, FUND


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.parse_args(argv)
    Rs, Rp, QV, FUND = load_inputs()
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    base = Params()
    runs = {
        "paper_btc (5bp)": base,
        "paper_pca1 (5bp)": replace(base, factor="pca1"),
        "btc crypto-cost 6bp": replace(base, cost_bps=6.0),
        "btc gross (0bp, no funding)": replace(base, cost_bps=0.0, funding=False),
        "btc Nagel high-vol only": replace(base, vol_condition="high_only"),
        "btc Nagel vol-scaled": replace(base, vol_condition="scale"),
    }
    out, series = {}, {}
    for k, p in runs.items():
        res = run(Rs, Rp, QV, FUND, p)
        res = res[res.index >= "2022-01-01"]
        out[k] = summarize(res)
        series[k] = res["net"]
    print(pd.DataFrame(out).T.round(3).to_string())
    S = pd.DataFrame(series)
    print("\nyearly Sharpe:\n", S.groupby(S.index.year).apply(lambda x: x.mean() / x.std() * np.sqrt(YEAR)).T.round(2).to_string())
    S.to_parquet("crypto_xsec/results/statarb_runs.parquet")


if __name__ == "__main__":
    main()
