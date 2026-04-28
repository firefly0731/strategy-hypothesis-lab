"""Adverse-threshold sensitivity analysis for hypothesis 1.

Sweeps ONE parameter over a fine-resolution range while holding the others fixed.
Outputs a table + simple ASCII chart so you can see how the result responds to
the chosen threshold.

Usage:
    # default: sweep adverse_bps from 0.5 to 20 in 30 steps
    python scripts/sensitivity_h1.py <run-dir>

    # sweep velocity window instead
    python scripts/sensitivity_h1.py <run-dir> --param velocity_window_sec --lo 0.5 --hi 60 --steps 20

    # sweep with custom fixed params
    python scripts/sensitivity_h1.py <run-dir> --velocity-window-sec 1 --threshold-quantile 0.75

The output table is also saved as CSV for plotting in the user's tool of choice.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats


def evaluate(
    trade: pl.DataFrame,
    *,
    velocity_window_sec: float,
    adverse_window_sec: float,
    adverse_bps: float,
    threshold_quantile: float,
) -> dict:
    W_ms = int(velocity_window_sec * 1000)
    Y_ms = int(adverse_window_sec * 1000)

    asks = trade.filter(pl.col("side") == "sell").sort("server_ts_ms")
    bids = trade.filter(pl.col("side") == "buy").sort("server_ts_ms")
    ask_t = asks["server_ts_ms"].to_numpy()
    ask_n = (asks["price"] * asks["qty"]).to_numpy()
    bid_t = bids["server_ts_ms"].to_numpy()
    bid_n = (bids["price"] * bids["qty"]).to_numpy()
    all_t = trade["server_ts_ms"].to_numpy()
    all_p = trade["price"].to_numpy()

    rows = []
    for r in trade.iter_rows(named=True):
        t = r["server_ts_ms"]
        side = r["side"]
        p_event = r["price"]
        if side == "sell":
            mask = (ask_t >= t - W_ms) & (ask_t < t)
            v = float(ask_n[mask].sum())
        elif side == "buy":
            mask = (bid_t >= t - W_ms) & (bid_t < t)
            v = float(bid_n[mask].sum())
        else:
            continue
        future_mask = (all_t > t) & (all_t <= t + Y_ms)
        if not future_mask.any():
            continue
        future_mean = float(all_p[future_mask].mean())
        move_bps = (future_mean - p_event) / p_event * 1e4
        adverse = (move_bps < -adverse_bps) if side == "sell" else (move_bps > adverse_bps)
        rows.append({"v": v, "adverse": adverse})

    if not rows:
        return {"error": "no rows"}
    df = pl.DataFrame(rows)
    threshold = float(df["v"].quantile(threshold_quantile))
    df = df.with_columns((pl.col("v") >= threshold).alias("signal"))
    tp = df.filter(pl.col("adverse") & pl.col("signal")).height
    fn = df.filter(pl.col("adverse") & ~pl.col("signal")).height
    fp = df.filter(~pl.col("adverse") & pl.col("signal")).height
    tn = df.filter(~pl.col("adverse") & ~pl.col("signal")).height
    n_adv = tp + fn
    n_non = fp + tn
    n = df.height
    if n_adv == 0 or n_non == 0:
        return {"n": n, "n_adv": n_adv, "tpr": 0.0, "fpr": 0.0, "lift": 0.0,
                "p_one": 1.0, "ci_lo": 0.0, "ci_hi": 0.0}
    tpr = tp / n_adv
    fpr = fp / n_non
    lift = tpr - fpr
    p_one = float(stats.fisher_exact([[tp, fn], [fp, tn]], alternative="greater").pvalue)
    rng = np.random.default_rng(42)
    boots = []
    adv_arr = np.array([1] * tp + [0] * fn)
    non_arr = np.array([1] * fp + [0] * tn)
    for _ in range(2000):
        a = rng.choice(adv_arr, n_adv, replace=True).mean()
        nn = rng.choice(non_arr, n_non, replace=True).mean()
        boots.append(a - nn)
    ci_lo, ci_hi = np.percentile(boots, [2.5, 97.5])
    return {
        "n": n, "n_adv": n_adv, "tpr": tpr, "fpr": fpr, "lift": lift,
        "p_one": p_one, "ci_lo": float(ci_lo), "ci_hi": float(ci_hi),
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    p.add_argument("--param", choices=["adverse_bps", "velocity_window_sec", "adverse_window_sec", "threshold_quantile"], default="adverse_bps")
    p.add_argument("--lo", type=float, default=None)
    p.add_argument("--hi", type=float, default=None)
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--velocity-window-sec", type=float, default=3.0)
    p.add_argument("--adverse-window-sec", type=float, default=60.0)
    p.add_argument("--adverse-bps", type=float, default=2.0)
    p.add_argument("--threshold-quantile", type=float, default=0.75)
    args = p.parse_args()

    defaults = {
        "adverse_bps": (0.5, 20.0),
        "velocity_window_sec": (0.5, 60.0),
        "adverse_window_sec": (5.0, 300.0),
        "threshold_quantile": (0.50, 0.95),
    }
    lo = args.lo if args.lo is not None else defaults[args.param][0]
    hi = args.hi if args.hi is not None else defaults[args.param][1]

    trade = pl.read_parquet(args.run_dir / "parquet" / "trade.parquet").sort("server_ts_ms")
    print(f"trade events: {trade.height}")
    print(f"sweeping {args.param}: [{lo}, {hi}] in {args.steps} steps")
    print(f"fixed: V={args.velocity_window_sec}s A={args.adverse_window_sec}s "
          f"bps={args.adverse_bps} q={args.threshold_quantile}")
    print()

    base = {
        "velocity_window_sec": args.velocity_window_sec,
        "adverse_window_sec": args.adverse_window_sec,
        "adverse_bps": args.adverse_bps,
        "threshold_quantile": args.threshold_quantile,
    }
    grid = np.linspace(lo, hi, args.steps)
    results = []
    print(f"{args.param:>22}  {'n':>5} {'adv':>5} {'TPR':>6} {'FPR':>6} {'LIFT':>7} {'CI95_lo':>8} {'CI95_hi':>8} {'p':>10}  bar")
    print("-" * 110)
    for x in grid:
        params = {**base, args.param: float(x)}
        m = evaluate(trade, **params)
        if "error" in m:
            continue
        m[args.param] = float(x)
        results.append(m)
        # ASCII bar: scale LIFT (-1 to +1) to 40 chars
        lift = m["lift"]
        bar_len = int(abs(lift) * 40)
        bar = ("+" * bar_len) if lift >= 0 else ("-" * bar_len)
        sig = "***" if m["p_one"] < 0.001 else "**" if m["p_one"] < 0.01 else "*" if m["p_one"] < 0.05 else ""
        print(f"{x:>22.4g}  {m['n']:>5d} {m['n_adv']:>5d} "
              f"{m['tpr']*100:>5.1f}% {m['fpr']*100:>5.1f}% "
              f"{lift*100:>+6.1f}% {m['ci_lo']*100:>+7.2f}% {m['ci_hi']*100:>+7.2f}% "
              f"{m['p_one']:>9.3g}{sig:>3} {bar}")

    if results:
        out_csv = args.run_dir / f"sensitivity_{args.param}.csv"
        cols = [args.param, "n", "n_adv", "tp", "fn", "fp", "tn", "tpr", "fpr", "lift", "ci_lo", "ci_hi", "p_one"]
        with out_csv.open("w") as f:
            f.write(",".join(cols) + "\n")
            for r in results:
                f.write(",".join(str(r.get(c, "")) for c in cols) + "\n")
        print(f"\nCSV saved: {out_csv}")


if __name__ == "__main__":
    main()
