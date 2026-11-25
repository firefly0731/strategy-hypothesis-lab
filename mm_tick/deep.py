"""Stage W: deeper quotes, one configuration chosen on 2026, confirmed on 2025. See DESIGN.md.

    python -m mm_tick.toxic build --depth K --tp-frac F                 # 2026 tables, 10 configurations
    python -m mm_tick.deep choose                                        # -> results/deep_model/choice.json
    python -m mm_tick.toxic build --depth K --tp-frac F --period early   # the chosen one only, 2025
    python -m mm_tick.deep confirm
"""
from __future__ import annotations

import argparse
import json
import logging

import numpy as np
import pandas as pd

from .bayes import FEATURES, TRAIN_TUNE, VALID, Bins, predict
from .depth import boot99
from .epnl import LAMBDAS, MIN_KEPT, deciles, normal_equations, rank_ic, ridge
from .run import RES
from .toxic import tag_for

DEPTHS = (40, 60, 80, 120, 160)
FRACS = (1.0, 0.5)
Y2026 = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10")
OUT = RES / "deep_model"
log = logging.getLogger("mm_tick.deep")


def table(k: int, f: float, period: str = "main") -> pd.DataFrame:
    df = pd.read_parquet(RES / f"toxic_features{tag_for(k, f, period)}.parquet")
    df["improved"] = df["improved"].astype(np.float32)
    return df


def describe(df: pd.DataFrame) -> dict:
    p = df["pnl_bp"].to_numpy().astype(np.float64)
    return {"trips": len(p), "trips_per_coin_day": len(p) / max(df[["sym", "day"]].drop_duplicates().shape[0], 1),
            "win_share": float((p >= 0).mean()), "mean_win": float(p[p >= 0].mean()),
            "mean_loss": float(p[p < 0].mean()), "by_tp_share": float(df["by_tp"].mean()), "mean": float(p.mean())}


def choose() -> dict:
    rows, months = [], []
    for k in DEPTHS:
        for f in FRACS:
            df = table(k, f)
            df = df[df["month"].isin(Y2026)]
            rows.append({"depth_bp": k, "tp_frac": f, **describe(df)})
            mo = df.groupby("month")["pnl_bp"].mean().rename(f"d{k}_f{f}")
            months.append(mo)
    res = pd.DataFrame(rows)
    ok = res[res["trips"] >= MIN_KEPT]
    best = ok.loc[ok["mean"].idxmax()]
    choice = {"depth_bp": int(best["depth_bp"]), "tp_frac": float(best["tp_frac"]), "mean_2026": float(best["mean"])}
    OUT.mkdir(exist_ok=True)
    res.to_csv(OUT / "choice_grid.csv", index=False)
    pd.concat(months, axis=1).to_csv(OUT / "choice_by_month.csv")
    (OUT / "choice.json").write_text(json.dumps(choice, indent=1))
    pd.set_option("display.width", 250)
    print(res.round(3).to_string(index=False))
    print(pd.concat(months, axis=1).round(2).to_string())
    print("chosen:", choice)
    return choice


def fit_2026(df: pd.DataFrame):
    """Stage E model: lambda by 2026-07 MSE from a 2026-05..06 fit, refit on 2026-05..10."""
    pnl = df["pnl_bp"].to_numpy().astype(np.float64)
    m = df["month"].to_numpy()
    tr, va = np.isin(m, TRAIN_TUNE), np.isin(m, VALID)
    bins = Bins(df[tr], features=FEATURES)
    A, b = normal_equations(bins.codes(df[tr]), bins, pnl[tr])
    c_va = bins.codes(df[va])
    mse = [float(np.mean((pnl[va] - predict(c_va, *ridge(A, b, lam), bins)) ** 2)) for lam in LAMBDAS]
    lam = LAMBDAS[int(np.argmin(mse))]
    full = np.isin(m, Y2026)
    bins = Bins(df[full], features=FEATURES)
    A, b = normal_equations(bins.codes(df[full]), bins, pnl[full])
    w, b0 = ridge(A, b, lam)
    return lam, bins, w, b0


def confirm() -> None:
    choice = json.loads((OUT / "choice.json").read_text())
    k, f = choice["depth_bp"], choice["tp_frac"]
    rng = np.random.default_rng(0)
    e = table(k, f, "early")
    p = e["pnl_bp"].to_numpy().astype(np.float64)
    day = e["day"].to_numpy()
    w1 = boot99(p, day, rng)
    lam, bins, w, b0 = fit_2026(table(k, f))
    pred = predict(bins.codes(e), w, b0, bins)
    keep = pred > 0
    w2 = boot99(p[keep], day[keep], rng)
    row = {"depth_bp": k, "tp_frac": f, **describe(e), "W1_mean": w1[0], "W1_lo99": w1[1], "W1_lo95": w1[2],
           "W1_hi95": w1[3], "lam": lam, "ic_2025": rank_ic(pred, p), "W2_kept": int(keep.sum()),
           "W2_mean": w2[0], "W2_lo99": w2[1], "W2_lo95": w2[2], "W2_hi95": w2[3]}
    row["pass_W1"] = bool(row["trips"] >= MIN_KEPT and w1[0] > 0 and w1[1] > 0)
    row["pass_W2"] = bool(row["W2_kept"] >= MIN_KEPT and w2[0] > 0 and w2[1] > 0)
    mo = e.groupby("month")["pnl_bp"].agg(["size", "mean"])
    gr = e.assign(group=np.where(e["tick_bp"] >= 3, "tick >= 3 bp", "tick < 3 bp")).groupby("group")["pnl_bp"] \
          .agg(["size", "mean"])
    dc = deciles(pred, p, (p < 0).astype(float))
    pd.DataFrame([row]).to_csv(OUT / "confirm.csv", index=False)
    mo.to_csv(OUT / "confirm_by_month.csv")
    gr.to_csv(OUT / "confirm_by_group.csv")
    dc.to_csv(OUT / "confirm_deciles.csv", index=False)
    print(pd.Series(row).to_string())
    print(mo.round(2).to_string())
    print(gr.round(2).to_string())
    print(dc.round(2).to_string(index=False))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["choose", "confirm"])
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    choose() if a.cmd == "choose" else confirm()


if __name__ == "__main__":
    main()
