"""Stage D: quote depth, alone (D1) and with the stage E state filter (D2). See DESIGN.md.

    python -m mm_tick.toxic build --depth 5     # (and 10, 20, 40) -> results/toxic_features_d<k>.parquet
    python -m mm_tick.depth fit
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from .bayes import TEST, TRAIN, TRAIN_TUNE, VALID, Bins, predict
from .epnl import LAMBDAS, MIN_KEPT, deciles, normal_equations, rank_ic, ridge
from .run import RES

DEPTHS = (0, 5, 10, 20, 40)
N_BOOT = 2000
log = logging.getLogger("mm_tick.depth")


def table(k: int) -> pd.DataFrame:
    df = pd.read_parquet(RES / ("toxic_features.parquet" if k == 0 else f"toxic_features_d{k}.parquet"))
    df["improved"] = df["improved"].astype(np.float32)
    return df


def boot99(pnl, day, rng):
    """Day-block bootstrap: (mean, 0.5%, 2.5%, 97.5%)."""
    if len(pnl) == 0:
        return np.nan, np.nan, np.nan, np.nan
    g = pd.DataFrame({"d": day, "p": pnl}).groupby("d")["p"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    idx = rng.integers(0, len(s), (N_BOOT, len(s)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return float(pnl.mean()), float(np.percentile(m, 0.5)), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def filter_model(df: pd.DataFrame):
    """Stage E model on this depth's trips; returns (lambda, test predictions, test mask)."""
    from .bayes import FEATURES
    pnl = df["pnl_bp"].to_numpy().astype(np.float64)
    m = df["month"].to_numpy()
    tr, va = np.isin(m, TRAIN_TUNE), np.isin(m, VALID)
    bins = Bins(df[tr], features=FEATURES)
    A, b = normal_equations(bins.codes(df[tr]), bins, pnl[tr])
    c_va = bins.codes(df[va])
    mse = []
    for lam in LAMBDAS:
        w, b0 = ridge(A, b, lam)
        mse.append(float(np.mean((pnl[va] - predict(c_va, w, b0, bins)) ** 2)))
    lam = LAMBDAS[int(np.argmin(mse))]
    tr, te = np.isin(m, TRAIN), np.isin(m, TEST)
    bins = Bins(df[tr], features=FEATURES)
    A, b = normal_equations(bins.codes(df[tr]), bins, pnl[tr])
    w, b0 = ridge(A, b, lam)
    return lam, predict(bins.codes(df[te]), w, b0, bins), te


def run() -> None:
    rng = np.random.default_rng(0)
    rows, months, groups, decs = [], [], [], []
    for k in DEPTHS:
        df = table(k)
        te = np.isin(df["month"].to_numpy(), TEST)
        pnl, day = df["pnl_bp"].to_numpy().astype(np.float64), df["day"].to_numpy()
        n_coin_days = df.loc[te, ["sym", "day"]].drop_duplicates().shape[0]
        d1 = boot99(pnl[te], day[te], rng)
        p_te = pnl[te]
        lam, pred, te2 = filter_model(df)
        keep = pred > 0
        d2 = boot99(p_te[keep], day[te][keep], rng)
        row = {"depth_bp": k, "trips_test": int(te.sum()), "trips_per_coin_day": te.sum() / max(n_coin_days, 1),
               "win_share": float((p_te >= 0).mean()), "mean_win": float(p_te[p_te >= 0].mean()),
               "mean_loss": float(p_te[p_te < 0].mean()), "by_tp_share": float(df.loc[te, "by_tp"].mean()),
               "D1_mean": d1[0], "D1_lo99": d1[1], "D1_lo95": d1[2], "D1_hi95": d1[3],
               "lam": lam, "ic_test": rank_ic(pred, p_te), "D2_kept": int(keep.sum()),
               "D2_mean": d2[0], "D2_lo99": d2[1], "D2_lo95": d2[2], "D2_hi95": d2[3]}
        row["pass_D1"] = bool(row["trips_test"] >= MIN_KEPT and d1[0] > 0 and d1[1] > 0)
        row["pass_D2"] = bool(row["D2_kept"] >= MIN_KEPT and d2[0] > 0 and d2[1] > 0)
        rows.append(row)
        x = df.loc[te, ["month", "pnl_bp", "tick_bp"]]
        mo = x.groupby("month")["pnl_bp"].agg(["size", "mean"]).reset_index()
        mo["depth_bp"] = k
        months.append(mo)
        gr = x.assign(group=np.where(x["tick_bp"] >= 3, "tick >= 3 bp", "tick < 3 bp")) \
              .groupby("group")["pnl_bp"].agg(["size", "mean"]).reset_index()
        gr["depth_bp"] = k
        groups.append(gr)
        dc = deciles(pred, p_te, (p_te < 0).astype(float))
        dc["depth_bp"] = k
        decs.append(dc)
        log.info("depth %d: %d test trips, D1 %.2f, D2 %.2f (%d kept)", k, te.sum(), d1[0], d2[0], keep.sum())
    out = RES / "depth_model"
    out.mkdir(exist_ok=True)
    res = pd.DataFrame(rows)
    res.to_csv(out / "result.csv", index=False)
    pd.concat(months).to_csv(out / "by_month.csv", index=False)
    pd.concat(groups).to_csv(out / "by_group.csv", index=False)
    pd.concat(decs).to_csv(out / "deciles.csv", index=False)
    pd.set_option("display.width", 250)
    print(res.round(3).to_string(index=False))
    print(pd.concat(months).pivot(index="month", columns="depth_bp", values="mean").round(2).to_string())
    print(pd.concat(groups).pivot(index="group", columns="depth_bp", values="mean").round(2).to_string())
    print(pd.concat(decs).pivot(index="q", columns="depth_bp", values="pnl").round(2).to_string())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit"])
    ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    run()


if __name__ == "__main__":
    main()
