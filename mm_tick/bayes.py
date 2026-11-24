"""Stage P, part 2: Bayesian additive logistic model of fill toxicity (see DESIGN.md).

    python -m mm_tick.bayes fit

Each feature enters as one-hot bins at its training deciles (NaN has its own bin); weights have a
Gaussian prior N(0, tau^2), the intercept a flat one. MAP by Newton's method; the Laplace
posterior gives the weight uncertainty. No sparse matrix library is needed: X'WX is assembled
from weighted contingency tables of the bin codes.
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from .ceiling import FRACS, auc, keep_rule
from .run import RES

FEATURES = (["ret_1s", "ret_5s", "ret_30s", "ret_120s", "ret_600s",
             "ofi_1s", "ofi_5s", "ofi_30s", "ofi_120s", "ofi_600s",
             "cnt_5s", "cnt_30s", "cnt_120s", "path_30s", "path_120s", "path_600s",
             "size_rel", "log_dt_last", "u", "dz", "need", "spread_ticks", "tick_bp", "improved",
             "hour_sin", "hour_cos", "loss7"])
TAUS = (0.1, 0.3, 1.0, 3.0, 10.0)
N_BINS = 10
TRAIN_TUNE = ("2026-05", "2026-06")
VALID = ("2026-07",)
TRAIN = ("2026-05", "2026-06", "2026-07")
TEST = ("2026-08", "2026-09", "2026-10")
log = logging.getLogger("mm_tick.bayes")


class Bins:
    """Decile edges per feature from the training rows; code = bin index, NaN -> last bin."""

    def __init__(self, df: pd.DataFrame, features=FEATURES, n_bins=N_BINS):
        self.features = list(features)
        self.edges = []
        for f in self.features:
            v = df[f].to_numpy(dtype=np.float64)
            v = v[np.isfinite(v)]
            e = np.unique(np.quantile(v, np.linspace(0, 1, n_bins + 1)[1:-1])) if len(v) else np.array([])
            self.edges.append(e)
        self.sizes = np.array([len(e) + 2 for e in self.edges])       # bins + NaN bin
        self.offsets = np.r_[0, np.cumsum(self.sizes)[:-1]]
        self.k = int(self.sizes.sum())

    def codes(self, df: pd.DataFrame) -> np.ndarray:
        out = np.empty((len(df), len(self.features)), dtype=np.int32)
        for j, (f, e) in enumerate(zip(self.features, self.edges)):
            v = df[f].to_numpy(dtype=np.float64)
            c = np.searchsorted(e, v, side="right")
            c[~np.isfinite(v)] = len(e) + 1
            out[:, j] = c                                          # local code
        return out


def _eta(codes, w, b0, offsets):
    eta = np.full(len(codes), b0)
    for j in range(codes.shape[1]):
        eta += w[offsets[j] + codes[:, j]]
    return eta


def fit_map(codes, y, bins: Bins, tau: float, max_iter: int = 50, tol: float = 1e-6):
    """Newton's method for the MAP; returns (w, b0, posterior covariance of [b0, w])."""
    k, off, sz = bins.k, bins.offsets, bins.sizes
    F = codes.shape[1]
    w = np.zeros(k)
    b0 = np.log(y.mean() / (1 - y.mean()))
    prec = np.r_[1e-6, np.full(k, 1.0 / tau ** 2)]
    for it in range(max_iter):
        p = 1.0 / (1.0 + np.exp(-_eta(codes, w, b0, off)))
        r = y - p
        wt = p * (1 - p)
        g = np.empty(k + 1)
        g[0] = r.sum()
        H = np.zeros((k + 1, k + 1))
        H[0, 0] = wt.sum()
        for j in range(F):
            cj = codes[:, j]
            sl = slice(1 + off[j], 1 + off[j] + sz[j])
            g[sl] = np.bincount(cj, r, minlength=sz[j])
            dj = np.bincount(cj, wt, minlength=sz[j])
            H[sl, sl] = np.diag(dj)
            H[0, sl] = H[sl, 0] = dj
            for i in range(j):
                ci = codes[:, i]
                sli = slice(1 + off[i], 1 + off[i] + sz[i])
                tab = np.bincount(ci * sz[j] + cj, wt, minlength=sz[i] * sz[j]).reshape(sz[i], sz[j])
                H[sli, sl] = tab
                H[sl, sli] = tab.T
        theta = np.r_[b0, w]
        g -= prec * theta
        A = H + np.diag(prec)
        step = np.linalg.solve(A, g)
        theta = theta + step
        b0, w = theta[0], theta[1:]
        if np.max(np.abs(step)) < tol:
            break
    cov = np.linalg.inv(A)
    log.info("tau %.2f: %d Newton steps", tau, it + 1)
    return w, b0, cov


def predict(codes, w, b0, bins: Bins):
    return _eta(codes, w, b0, bins.offsets)


def run() -> None:
    df = pd.read_parquet(RES / "toxic_features.parquet")
    df["improved"] = df["improved"].astype(np.float32)
    y_all = df["y"].to_numpy().astype(np.float64)
    m = df["month"].to_numpy()
    # 1) prior scale on the last design month
    tr, va = np.isin(m, TRAIN_TUNE), np.isin(m, VALID)
    bins = Bins(df[tr])
    c_tr, c_va = bins.codes(df[tr]), bins.codes(df[va])
    tune = []
    for tau in TAUS:
        w, b0, _ = fit_map(c_tr, y_all[tr], bins, tau)
        tune.append({"tau": tau, "auc_valid": auc(predict(c_va, w, b0, bins), y_all[va])})
    tune = pd.DataFrame(tune)
    tau = float(tune.loc[tune["auc_valid"].idxmax(), "tau"])
    # 2) refit on the whole design half, test on the confirm half
    tr, te = np.isin(m, TRAIN), np.isin(m, TEST)
    bins = Bins(df[tr])
    c_tr, c_te = bins.codes(df[tr]), bins.codes(df[te])
    w, b0, cov = fit_map(c_tr, y_all[tr], bins, tau)
    s_tr, s_te = predict(c_tr, w, b0, bins), predict(c_te, w, b0, bins)
    res = {"tau": tau, "auc_train": auc(s_tr, y_all[tr]), "auc_test": auc(s_te, y_all[te]),
           "n_train": int(tr.sum()), "n_test": int(te.sum()), "loss_share_test": y_all[te].mean()}
    by_month = pd.DataFrame([{"month": mo, "auc": auc(s_te[m[te] == mo], y_all[te][m[te] == mo])}
                             for mo in TEST])
    big = df.loc[te, "tick_bp"].to_numpy() >= 3
    by_group = pd.DataFrame([{"group": g, "n": int(k_.sum()), "auc": auc(s_te[k_], y_all[te][k_])}
                             for g, k_ in (("tick >= 3 bp", big), ("tick < 3 bp", ~big))])
    # calibration on the test half
    p_te = 1 / (1 + np.exp(-s_te))
    q = pd.qcut(p_te, 10, labels=False, duplicates="drop")
    calib = pd.DataFrame({"pred": p_te, "y": y_all[te], "q": q}).groupby("q").mean()
    # feature importance: range of the bin weights (excluding the NaN bin) and its posterior sd
    sd = np.sqrt(np.diag(cov))[1:]
    imp = []
    for j, f in enumerate(bins.features):
        sl = slice(bins.offsets[j], bins.offsets[j] + bins.sizes[j] - 1)
        imp.append({"feature": f, "range": float(w[sl].max() - w[sl].min()), "max_sd": float(sd[sl].max()),
                    "auc_test_alone": auc(df.loc[te, f].fillna(df.loc[tr, f].median()).to_numpy(), y_all[te])})
    imp = pd.DataFrame(imp).sort_values("range", ascending=False)
    # economic check (stage C rule with the real score; descriptive unless P1 passes)
    pnl = df["pnl_bp"].to_numpy().astype(np.float64)
    goodness = -np.r_[s_tr, s_te]
    pnl2 = np.r_[pnl[tr], pnl[te]]
    design = np.r_[np.ones(tr.sum(), bool), np.zeros(te.sum(), bool)]
    f, thr = keep_rule(goodness, pnl2, design)
    kept = (~design) & (goodness >= thr)
    econ = {"frac_design": f, "kept_test": kept.sum() / (~design).sum(), "pnl_test_kept": pnl2[kept].mean(),
            "pnl_test_all": pnl2[~design].mean()}
    out = RES / "toxic_model"
    out.mkdir(exist_ok=True)
    tune.to_csv(out / "tune.csv", index=False)
    pd.DataFrame([res]).to_csv(out / "result.csv", index=False)
    by_month.to_csv(out / "by_month.csv", index=False)
    by_group.to_csv(out / "by_group.csv", index=False)
    calib.to_csv(out / "calibration.csv")
    imp.to_csv(out / "features.csv", index=False)
    pd.DataFrame([econ]).to_csv(out / "economic.csv", index=False)
    pd.set_option("display.width", 200)
    for name, x in (("tune", tune), ("result", pd.DataFrame([res])), ("by month", by_month),
                    ("by group", by_group), ("calibration", calib), ("features", imp),
                    ("economic", pd.DataFrame([econ]))):
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
