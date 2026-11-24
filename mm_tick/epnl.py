"""Stage E: a Bayesian additive model of expected round-trip PnL (see DESIGN.md).

    python -m mm_tick.epnl fit

Same features and bins as stage P. Posterior mean of a Gaussian linear model with a Gaussian prior
on the bin weights = ridge on one-hot bins; X'X is assembled from bin contingency tables.
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from .bayes import TEST, TRAIN, TRAIN_TUNE, VALID, Bins, fit_map, predict
from .run import RES

LAMBDAS = (1.0, 10.0, 100.0, 1e3, 1e4, 1e5)
FRACS_E = (0.01, 0.02, 0.05, 0.1, 0.2)
MIN_KEPT = 2000
N_BOOT = 2000
log = logging.getLogger("mm_tick.epnl")


def normal_equations(codes, bins: Bins, y):
    """X'X and X'y for X = [1, one-hot bins]."""
    k, off, sz = bins.k, bins.offsets, bins.sizes
    F = codes.shape[1]
    A = np.zeros((k + 1, k + 1))
    b = np.empty(k + 1)
    A[0, 0], b[0] = len(y), y.sum()
    for j in range(F):
        cj = codes[:, j]
        sl = slice(1 + off[j], 1 + off[j] + sz[j])
        dj = np.bincount(cj, minlength=sz[j]).astype(np.float64)
        b[sl] = np.bincount(cj, y, minlength=sz[j])
        A[sl, sl] = np.diag(dj)
        A[0, sl] = A[sl, 0] = dj
        for i in range(j):
            ci = codes[:, i]
            sli = slice(1 + off[i], 1 + off[i] + sz[i])
            tab = np.bincount(ci * sz[j] + cj, minlength=sz[i] * sz[j]).reshape(sz[i], sz[j])
            A[sli, sl] = tab
            A[sl, sli] = tab.T
    return A, b


def ridge(A, b, lam):
    """Posterior mean with prior precision ratio lam on the bin weights, flat intercept."""
    pen = np.r_[0.0, np.full(len(b) - 1, lam)]
    theta = np.linalg.solve(A + np.diag(pen), b)
    return theta[1:], theta[0]


def rank_ic(a, b):
    return float(np.corrcoef(pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy())[0, 1])


def day_boot(pnl, day, rng, n=N_BOOT):
    """Day-block bootstrap of the mean of pnl; returns (mean, 2.5%, 97.5%)."""
    if len(pnl) == 0:
        return np.nan, np.nan, np.nan
    g = pd.DataFrame({"d": day, "p": pnl}).groupby("d")["p"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    idx = rng.integers(0, len(s), (n, len(s)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return float(pnl.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def deciles(pred, pnl, y):
    q = pd.qcut(pd.Series(pred).rank(method="first"), 10, labels=False)
    return (pd.DataFrame({"q": q, "pred": pred, "pnl": pnl, "loss": y}).groupby("q")
            .agg(n=("pnl", "size"), pred=("pred", "mean"), pnl=("pnl", "mean"), loss_share=("loss", "mean"))
            .reset_index())


def run() -> None:
    df = pd.read_parquet(RES / "toxic_features.parquet")
    df["improved"] = df["improved"].astype(np.float32)
    pnl = df["pnl_bp"].to_numpy().astype(np.float64)
    y = df["y"].to_numpy().astype(np.float64)
    m = df["month"].to_numpy()
    day = df["day"].to_numpy()
    rng = np.random.default_rng(0)
    # 1) prior ratio on 2026-07 with a May-Jun fit
    tr, va = np.isin(m, TRAIN_TUNE), np.isin(m, VALID)
    bins = Bins(df[tr])
    c_tr, c_va = bins.codes(df[tr]), bins.codes(df[va])
    A, b = normal_equations(c_tr, bins, pnl[tr])
    tune = []
    for lam in LAMBDAS:
        w, b0 = ridge(A, b, lam)
        p_va = predict(c_va, w, b0, bins)
        tune.append({"lam": lam, "mse_valid": float(np.mean((pnl[va] - p_va) ** 2)),
                     "ic_valid": rank_ic(p_va, pnl[va]), "kept_valid": float((p_va > 0).mean()),
                     "pnl_kept_valid": float(pnl[va][p_va > 0].mean()) if (p_va > 0).any() else np.nan})
    tune = pd.DataFrame(tune)
    lam = float(tune.loc[tune["mse_valid"].idxmin(), "lam"])
    w, b0 = ridge(A, b, lam)
    p_va = predict(c_va, w, b0, bins)
    frac_rows = []
    for f in FRACS_E:
        k_ = p_va >= np.quantile(p_va, 1 - f)
        frac_rows.append({"frac": f, "pnl_valid": float(pnl[va][k_].mean())})
    frac_tab = pd.DataFrame(frac_rows)
    f_best = float(frac_tab.loc[frac_tab["pnl_valid"].idxmax(), "frac"])
    # 2) refit on 2026-05..07, test on 2026-08..10
    tr, te = np.isin(m, TRAIN), np.isin(m, TEST)
    bins = Bins(df[tr])
    c_tr, c_te = bins.codes(df[tr]), bins.codes(df[te])
    A, b = normal_equations(c_tr, bins, pnl[tr])
    w, b0 = ridge(A, b, lam)
    s_tr, s_te = predict(c_tr, w, b0, bins), predict(c_te, w, b0, bins)
    pnl_te, day_te, y_te, m_te = pnl[te], day[te], y[te], m[te]
    keep = s_te > 0
    mean_k, lo_k, hi_k = day_boot(pnl_te[keep], day_te[keep], rng)
    mean_a, lo_a, hi_a = day_boot(pnl_te, day_te, rng)
    e1 = bool(keep.sum() >= MIN_KEPT and mean_k > 0 and lo_k > 0)
    res = {"lam": lam, "ic_train": rank_ic(s_tr, pnl[tr]), "ic_test": rank_ic(s_te, pnl_te),
           "kept_test": int(keep.sum()), "kept_share": float(keep.mean()), "pnl_kept": mean_k,
           "pnl_kept_lo": lo_k, "pnl_kept_hi": hi_k, "pnl_all": mean_a, "pnl_all_lo": lo_a,
           "n_sym_kept": int(df.loc[te, "sym"][keep].nunique()), "E1": e1}
    by_month = pd.DataFrame([{"month": mo, "ic": rank_ic(s_te[m_te == mo], pnl_te[m_te == mo]),
                              "kept": int((keep & (m_te == mo)).sum()),
                              "pnl_kept": float(pnl_te[keep & (m_te == mo)].mean()) if (keep & (m_te == mo)).any()
                              else np.nan}
                             for mo in TEST])
    dec = deciles(s_te, pnl_te, y_te)
    # descriptive: the kept fraction chosen on 2026-07, threshold from the refit model on 2026-07
    va2 = np.isin(m[tr], VALID)
    thr = np.quantile(s_tr[va2], 1 - f_best)
    kf = s_te >= thr
    mf, lf, hf = day_boot(pnl_te[kf], day_te[kf], rng)
    frac_res = {"frac_chosen": f_best, "kept_test": int(kf.sum()), "pnl_kept": mf, "lo": lf, "hi": hf}
    # 3) secondary: two-part model
    tau = float(pd.read_csv(RES / "toxic_model" / "result.csv")["tau"].iloc[0])
    wl, bl, _ = fit_map(c_tr, y[tr], bins, tau)
    p_loss = 1 / (1 + np.exp(-predict(c_te, wl, bl, bins)))
    parts = {}
    for nm, sel in (("win", y[tr] == 0), ("loss", y[tr] == 1)):
        A2, b2 = normal_equations(c_tr[sel], bins, pnl[tr][sel])
        w2, b02 = ridge(A2, b2, lam)
        parts[nm] = predict(c_te, w2, b02, bins)
    s2 = (1 - p_loss) * parts["win"] + p_loss * parts["loss"]
    k2 = s2 > 0
    m2, l2, h2 = day_boot(pnl_te[k2], day_te[k2], rng)
    sec = {"ic_test": rank_ic(s2, pnl_te), "kept_test": int(k2.sum()), "pnl_kept": m2, "lo": l2, "hi": h2}
    dec2 = deciles(s2, pnl_te, y_te)
    out = RES / "epnl_model"
    out.mkdir(exist_ok=True)
    tune.to_csv(out / "tune.csv", index=False)
    frac_tab.to_csv(out / "frac_valid.csv", index=False)
    pd.DataFrame([res]).to_csv(out / "result.csv", index=False)
    by_month.to_csv(out / "by_month.csv", index=False)
    dec.to_csv(out / "deciles.csv", index=False)
    pd.DataFrame([frac_res]).to_csv(out / "frac_test.csv", index=False)
    pd.DataFrame([sec]).to_csv(out / "two_part.csv", index=False)
    dec2.to_csv(out / "two_part_deciles.csv", index=False)
    pd.set_option("display.width", 220)
    for name, x in (("tune", tune), ("frac on valid", frac_tab), ("result", pd.DataFrame([res])),
                    ("by month", by_month), ("deciles", dec), ("frac on test", pd.DataFrame([frac_res])),
                    ("two-part", pd.DataFrame([sec])), ("two-part deciles", dec2)):
        print("==", name)
        print(x.round(4).to_string())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit"])
    ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    run()


if __name__ == "__main__":
    main()
