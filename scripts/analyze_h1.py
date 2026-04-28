"""Hypothesis 1 verification: Trade Velocity Filter against live MM bot fills.

Loads Parquet from a captured run-dir, computes trade velocity, identifies own
fills, judges adverse outcomes, and reports counterfactual filter effectiveness.

Methodology
-----------
Velocity score (per timestamp t):
    sell_velocity(t) = sum(trade_volume * trade_price where ask_bid='ASK' in [t-W, t])  # KRW notional
    buy_velocity(t)  = sum(trade_volume * trade_price where ask_bid='BID' in [t-W, t])

For each own fill (myOrder where state='done'):
    - If ask_bid='BID' (we BOUGHT — maker bid hit by aggressor sell):
        * check sell_velocity at fill time → "signal active" if > threshold
        * adverse if mean trade price in next Y sec drops by more than X bps from fill price
    - If ask_bid='ASK' (we SOLD — maker ask hit by aggressor buy):
        * check buy_velocity at fill time → "signal active" if > threshold
        * adverse if mean trade price in next Y sec rises by more than X bps from fill price

Counterfactual confusion matrix:
                       signal_active  | signal_inactive
    was_adverse           TP           |    FN
    not_adverse           FP           |    TN

    Sensitivity (TPR) = TP/(TP+FN)  — % of adverse fills the filter would have caught
    Specificity (TNR) = TN/(TN+FP)  — % of non-adverse fills the filter correctly let through
    Lift             = TPR − FPR    — overall filter value (>0 means useful)

Usage:
    python scripts/analyze_h1.py <run-dir> [options]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    p.add_argument("--velocity-window-sec", type=float, default=5.0,
                   help="Lookback window for velocity calculation")
    p.add_argument("--adverse-window-sec", type=float, default=30.0,
                   help="Look-ahead window for adverse outcome judgment")
    p.add_argument("--adverse-bps", type=float, default=5.0,
                   help="Adverse threshold in basis points (1 bp = 0.01%)")
    p.add_argument("--velocity-threshold-quantile", type=float, default=0.75,
                   help="Quantile of velocity scores at fill times to use as 'signal active' threshold")
    args = p.parse_args()

    rd = args.run_dir
    parquet_dir = rd / "parquet"
    if not parquet_dir.exists():
        sys.exit(f"parquet dir not found: {parquet_dir} — run convert.py first")

    trade = pl.read_parquet(parquet_dir / "trade.parquet")
    my_order = pl.read_parquet(parquet_dir / "myOrder.parquet")

    print(f"=== Inputs ===")
    print(f"  trade events:    {trade.height}")
    print(f"  myOrder events:  {my_order.height}")
    print()

    # Filter own fills (state='done' = fully executed)
    fills = my_order.filter(pl.col("state") == "done")
    print(f"  fills (state=done): {fills.height}")
    if fills.height == 0:
        sys.exit("no fills captured; cannot run analysis")
    print(f"  side breakdown:")
    print(fills.group_by("side").agg(pl.len().alias("n")))
    print()

    # Use server timestamp for both. trade has server_ts_ms; my_order has server_ts_ms (timestamp from raw).
    # For trade, server_ts_ms = top-level 'timestamp' (ms); for myOrder, same field name.
    # Sort each by time.
    trade = trade.sort("server_ts_ms")
    fills = fills.sort("server_ts_ms")

    # Convert windows to ms
    W_ms = int(args.velocity_window_sec * 1000)
    Y_ms = int(args.adverse_window_sec * 1000)

    # Helper: for each fill timestamp T, compute:
    #   sell_vol(T) = sum(trade_volume * trade_price where ask_bid='ASK' in [T-W, T])
    #   buy_vol(T)  = sum(trade_volume * trade_price where ask_bid='BID' in [T-W, T])
    # Then choose the relevant velocity per fill side.

    # Pre-split trades by side
    asks = trade.filter(pl.col("side") == "sell")  # ask_bid='ASK' → side='sell' in our convert
    bids = trade.filter(pl.col("side") == "buy")

    def velocity_at(t_ms: int, side_trades: pl.DataFrame) -> float:
        sub = side_trades.filter(
            (pl.col("server_ts_ms") >= t_ms - W_ms) & (pl.col("server_ts_ms") <= t_ms)
        )
        if sub.height == 0:
            return 0.0
        return float((sub["price"] * sub["qty"]).sum())

    # Per-fill table
    rows = []
    for r in fills.iter_rows(named=True):
        t = r["server_ts_ms"]
        side = r["side"]                 # 'buy' (BID fill) or 'sell' (ASK fill)
        fill_price = r["price"]

        if side == "buy":
            # We bought (BID maker filled) → check sell pressure
            v = velocity_at(t, asks)
            relevant_velocity = "sell"
        elif side == "sell":
            # We sold (ASK maker filled) → check buy pressure
            v = velocity_at(t, bids)
            relevant_velocity = "buy"
        else:
            continue

        # Future trades for adverse classification
        future = trade.filter(
            (pl.col("server_ts_ms") > t) & (pl.col("server_ts_ms") <= t + Y_ms)
        )
        if future.height == 0:
            future_mean_price = None
            adverse = None
        else:
            future_mean_price = float(future["price"].mean())
            move_bps = (future_mean_price - fill_price) / fill_price * 1e4
            if side == "buy":
                # Adverse for buyer = price went DOWN
                adverse = bool(move_bps < -args.adverse_bps)
            else:  # sell
                # Adverse for seller = price went UP
                adverse = bool(move_bps > args.adverse_bps)

        rows.append({
            "fill_ts_ms": t,
            "side": side,
            "fill_price": fill_price,
            "velocity_kind": relevant_velocity,
            "velocity_krw": v,
            "future_mean_price": future_mean_price,
            "adverse": adverse,
        })

    df = pl.DataFrame(rows)
    if df.height == 0:
        sys.exit("no fills produced rows; check side mapping")

    # Drop rows where adverse couldn't be judged (too close to capture end)
    judged = df.filter(pl.col("adverse").is_not_null())
    print(f"  fills judged for adverse: {judged.height} (dropped {df.height - judged.height} near-end)")
    if judged.height == 0:
        sys.exit("no judgeable fills")

    # Determine velocity threshold (per quantile of fill-time velocities)
    threshold = float(judged["velocity_krw"].quantile(args.velocity_threshold_quantile))
    print(f"  velocity threshold ({int(args.velocity_threshold_quantile*100)}th percentile) = {threshold:.0f} KRW")
    print()

    judged = judged.with_columns((pl.col("velocity_krw") >= threshold).alias("signal_active"))

    tp = judged.filter(pl.col("adverse") & pl.col("signal_active")).height
    fn = judged.filter(pl.col("adverse") & ~pl.col("signal_active")).height
    fp = judged.filter(~pl.col("adverse") & pl.col("signal_active")).height
    tn = judged.filter(~pl.col("adverse") & ~pl.col("signal_active")).height

    n = judged.height
    n_adv = tp + fn
    n_non = fp + tn
    base_rate = n_adv / n if n else 0.0

    tpr = tp / n_adv if n_adv else 0.0
    fpr = fp / n_non if n_non else 0.0
    tnr = tn / n_non if n_non else 0.0

    print("=== Confusion Matrix (counterfactual) ===")
    print(f"                signal_active   signal_inactive")
    print(f"  was_adverse        {tp:6d}             {fn:6d}    (n_adverse = {n_adv})")
    print(f"  not_adverse        {fp:6d}             {tn:6d}    (n_non = {n_non})")
    print()
    print(f"  Total judged fills:        {n}")
    print(f"  Base rate (adverse %):     {base_rate*100:5.1f}%")
    print(f"  Sensitivity (TPR, recall): {tpr*100:5.1f}%   ← would catch this % of adverse fills")
    print(f"  False positive rate (FPR): {fpr*100:5.1f}%   ← would mis-cancel this % of good fills")
    print(f"  Specificity (TNR):         {tnr*100:5.1f}%")
    print(f"  LIFT (TPR − FPR):          {(tpr-fpr)*100:+5.1f} pp   ← > 0 means filter is informative")
    print()

    # Export per-fill detail CSV
    out_csv = rd / "h1_per_fill.csv"
    judged.write_csv(out_csv)
    print(f"  per-fill detail: {out_csv}")

    # Summary JSON
    summary = {
        "run_dir": str(rd),
        "params": vars(args),
        "n_total_fills": fills.height,
        "n_judged": n,
        "n_adverse": n_adv,
        "base_rate_adverse": base_rate,
        "velocity_threshold_krw": threshold,
        "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
        "metrics": {"tpr": tpr, "fpr": fpr, "tnr": tnr, "lift": tpr - fpr},
    }
    out_json = rd / "h1_summary.json"
    out_json.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  summary:        {out_json}")


if __name__ == "__main__":
    main()
