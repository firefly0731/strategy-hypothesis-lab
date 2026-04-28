"""Parameter sweep for analyze_h1.

Runs analyze_h1 over a grid of (velocity_window_sec, adverse_window_sec,
adverse_bps, threshold_quantile) values to find the parameter combination
with the highest LIFT (TPR − FPR). Useful for sensitivity analysis and to
defend a chosen parameter set in a presentation.

Usage:
    python scripts/sweep_h1.py <run-dir>

Reads the same parquet files analyze_h1 reads. Does NOT re-run the analysis
script — it reimplements the core computation in-memory for speed and varies
parameters without writing intermediate files.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import polars as pl


VELOCITY_WINDOWS = [1.0, 3.0, 5.0, 10.0, 30.0]
ADVERSE_WINDOWS = [10.0, 30.0, 60.0, 180.0]
ADVERSE_BPS_VALUES = [2.0, 5.0, 10.0, 20.0]
THRESHOLD_QUANTILES = [0.50, 0.66, 0.75, 0.90]


def evaluate_one(
    trade: pl.DataFrame,
    fills: pl.DataFrame,
    *,
    velocity_window_sec: float,
    adverse_window_sec: float,
    adverse_bps: float,
    threshold_quantile: float,
) -> dict | None:
    W_ms = int(velocity_window_sec * 1000)
    Y_ms = int(adverse_window_sec * 1000)

    asks = trade.filter(pl.col("side") == "sell")
    bids = trade.filter(pl.col("side") == "buy")

    rows = []
    for r in fills.iter_rows(named=True):
        t = r["server_ts_ms"]
        side = r["side"]
        fill_price = r["price"]

        if side == "buy":
            sub = asks.filter(
                (pl.col("server_ts_ms") >= t - W_ms) & (pl.col("server_ts_ms") <= t)
            )
            v = float((sub["price"] * sub["qty"]).sum()) if sub.height else 0.0
        elif side == "sell":
            sub = bids.filter(
                (pl.col("server_ts_ms") >= t - W_ms) & (pl.col("server_ts_ms") <= t)
            )
            v = float((sub["price"] * sub["qty"]).sum()) if sub.height else 0.0
        else:
            continue

        future = trade.filter(
            (pl.col("server_ts_ms") > t) & (pl.col("server_ts_ms") <= t + Y_ms)
        )
        if future.height == 0:
            continue
        future_mean = float(future["price"].mean())
        move_bps = (future_mean - fill_price) / fill_price * 1e4
        if side == "buy":
            adverse = move_bps < -adverse_bps
        else:
            adverse = move_bps > adverse_bps
        rows.append({"v": v, "adverse": adverse})

    if not rows:
        return None
    df = pl.DataFrame(rows)
    threshold = float(df["v"].quantile(threshold_quantile))
    df = df.with_columns((pl.col("v") >= threshold).alias("signal"))

    tp = df.filter(pl.col("adverse") & pl.col("signal")).height
    fn = df.filter(pl.col("adverse") & ~pl.col("signal")).height
    fp = df.filter(~pl.col("adverse") & pl.col("signal")).height
    tn = df.filter(~pl.col("adverse") & ~pl.col("signal")).height

    n_adv = tp + fn
    n_non = fp + tn
    tpr = tp / n_adv if n_adv else 0.0
    fpr = fp / n_non if n_non else 0.0
    lift = tpr - fpr

    return {
        "n_judged": df.height,
        "n_adverse": n_adv,
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "tpr": round(tpr, 4),
        "fpr": round(fpr, 4),
        "lift": round(lift, 4),
        "base_rate": round(n_adv / df.height, 4),
        "threshold_krw": round(threshold, 0),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    args = p.parse_args()

    parquet_dir = args.run_dir / "parquet"
    trade = pl.read_parquet(parquet_dir / "trade.parquet").sort("server_ts_ms")
    my_order = pl.read_parquet(parquet_dir / "myOrder.parquet").sort("server_ts_ms")
    fills = my_order.filter(pl.col("state") == "done")

    print(f"trade rows: {trade.height},  fills (state=done): {fills.height}")
    if fills.height == 0:
        sys.exit("no fills — cannot run sweep")
    print()

    results = []
    grid = list(itertools.product(VELOCITY_WINDOWS, ADVERSE_WINDOWS, ADVERSE_BPS_VALUES, THRESHOLD_QUANTILES))
    print(f"sweep grid: {len(grid)} combinations")
    for vw, aw, abps, tq in grid:
        m = evaluate_one(
            trade, fills,
            velocity_window_sec=vw, adverse_window_sec=aw,
            adverse_bps=abps, threshold_quantile=tq,
        )
        if m is None:
            continue
        m.update({
            "velocity_window_sec": vw, "adverse_window_sec": aw,
            "adverse_bps": abps, "threshold_quantile": tq,
        })
        results.append(m)

    if not results:
        sys.exit("no valid results")

    # Sort by lift desc, then by sample size desc
    results.sort(key=lambda r: (-r["lift"], -r["n_judged"]))

    print()
    print("=== TOP 10 by LIFT ===")
    print(f"{'V_win':>6} {'A_win':>6} {'A_bps':>6} {'q':>5} {'n':>5} {'adv':>4} {'TPR':>6} {'FPR':>6} {'LIFT':>7}")
    for r in results[:10]:
        print(f"{r['velocity_window_sec']:>6.1f} {r['adverse_window_sec']:>6.1f} {r['adverse_bps']:>6.1f} "
              f"{r['threshold_quantile']:>5.2f} {r['n_judged']:>5d} {r['n_adverse']:>4d} "
              f"{r['tpr']*100:>5.1f}% {r['fpr']*100:>5.1f}% {r['lift']*100:>+5.1f}pp")

    out = args.run_dir / "h1_sweep.json"
    out.write_text(json.dumps(results, indent=2))
    print()
    print(f"full sweep saved: {out}  ({len(results)} rows)")


if __name__ == "__main__":
    main()
