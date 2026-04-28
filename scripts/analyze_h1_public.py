"""Hypothesis 1 verification using PUBLIC trade tape only.

Treats every public trade as a hypothetical maker fill event:
  - ASK aggressor (side='sell' in our convert): a maker BID got filled → maker BOUGHT.
                    Adverse for maker if mean future price DROPS.
  - BID aggressor (side='buy'): a maker ASK got filled → maker SOLD.
                    Adverse for maker if mean future price RISES.

Velocity is computed STRICTLY BEFORE the event (lookback window) to avoid
self-correlation. Adverse is computed STRICTLY AFTER the event.

n is now ~2,000+ events instead of ~30 own fills → real statistical power.

Usage:
    python scripts/analyze_h1_public.py <run-dir> [options]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl
import numpy as np
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

    # Pre-extract numpy arrays for fast windowed computation
    ask_t = asks["server_ts_ms"].to_numpy()
    ask_notional = (asks["price"] * asks["qty"]).to_numpy()
    bid_t = bids["server_ts_ms"].to_numpy()
    bid_notional = (bids["price"] * bids["qty"]).to_numpy()
    all_t = trade["server_ts_ms"].to_numpy()
    all_p = trade["price"].to_numpy()

    rows = []
    for r in trade.iter_rows(named=True):
        t = r["server_ts_ms"]
        side = r["side"]
        p_event = r["price"]

        # Velocity: same-side notional in [t-W, t) (strict < t, so the event itself is excluded)
        if side == "sell":
            # ASK aggressor → maker BOUGHT → check sell-pressure (other ASK aggressors before)
            mask = (ask_t >= t - W_ms) & (ask_t < t)
            v = float(ask_notional[mask].sum())
        elif side == "buy":
            mask = (bid_t >= t - W_ms) & (bid_t < t)
            v = float(bid_notional[mask].sum())
        else:
            continue

        # Adverse: future trades in (t, t+Y]
        future_mask = (all_t > t) & (all_t <= t + Y_ms)
        if not future_mask.any():
            continue
        future_mean = float(all_p[future_mask].mean())
        move_bps = (future_mean - p_event) / p_event * 1e4
        if side == "sell":
            # Maker bought at p_event; adverse if mean future drops by > adverse_bps
            adverse = move_bps < -adverse_bps
        else:  # 'buy' aggressor → maker sold; adverse if rises
            adverse = move_bps > adverse_bps
        rows.append({"v": v, "adverse": adverse})

    if not rows:
        return {"error": "no rows produced"}

    df = pl.DataFrame(rows)
    threshold = float(df["v"].quantile(threshold_quantile))
    df = df.with_columns((pl.col("v") >= threshold).alias("signal"))

    tp = df.filter(pl.col("adverse") & pl.col("signal")).height
    fn = df.filter(pl.col("adverse") & ~pl.col("signal")).height
    fp = df.filter(~pl.col("adverse") & pl.col("signal")).height
    tn = df.filter(~pl.col("adverse") & ~pl.col("signal")).height

    n_adv = tp + fn
    n_non = fp + tn
    n_total = df.height
    tpr = tp / n_adv if n_adv else 0.0
    fpr = fp / n_non if n_non else 0.0
    lift = tpr - fpr
    base_rate = n_adv / n_total

    # Statistical tests
    table = [[tp, fn], [fp, tn]]
    fisher_one = stats.fisher_exact(table, alternative="greater")
    fisher_two = stats.fisher_exact(table, alternative="two-sided")
    try:
        chi2, p_chi, _, _ = stats.chi2_contingency(table, correction=True)
    except Exception:
        chi2, p_chi = float("nan"), float("nan")

    # Bootstrap 95% CI on LIFT
    rng = np.random.default_rng(42)
    B = 5000
    adv_signals = np.array([1] * tp + [0] * fn)
    non_signals = np.array([1] * fp + [0] * tn)
    boot_lifts = []
    for _ in range(B):
        a = rng.choice(adv_signals, size=n_adv, replace=True).mean() if n_adv else 0.0
        n = rng.choice(non_signals, size=n_non, replace=True).mean() if n_non else 0.0
        boot_lifts.append(a - n)
    ci_lo, ci_hi = np.percentile(boot_lifts, [2.5, 97.5])

    return {
        "n_total": n_total,
        "n_adverse": n_adv,
        "base_rate": round(base_rate, 4),
        "threshold_krw": round(threshold, 0),
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "tpr": round(tpr, 4),
        "fpr": round(fpr, 4),
        "lift": round(lift, 4),
        "fisher_one_sided_p": round(float(fisher_one.pvalue), 6),
        "fisher_two_sided_p": round(float(fisher_two.pvalue), 6),
        "fisher_odds_ratio": round(float(fisher_one.statistic), 3),
        "chi2": round(float(chi2), 3),
        "chi2_p": round(float(p_chi), 6),
        "lift_ci95_lo": round(float(ci_lo), 4),
        "lift_ci95_hi": round(float(ci_hi), 4),
    }


def fmt(metrics: dict, params: dict) -> str:
    p1 = metrics["fisher_one_sided_p"]
    sig = "***" if p1 < 0.001 else "**" if p1 < 0.01 else "*" if p1 < 0.05 else ""
    return (
        f"  V={params['velocity_window_sec']:>4.1f}s  A={params['adverse_window_sec']:>5.1f}s  "
        f"±{params['adverse_bps']:>4.1f}bp  q={params['threshold_quantile']:.2f}  "
        f"|  n={metrics['n_total']:>4d}  adv={metrics['n_adverse']:>4d} ({metrics['base_rate']*100:.1f}%)  "
        f"|  TPR={metrics['tpr']*100:>4.1f}%  FPR={metrics['fpr']*100:>4.1f}%  "
        f"LIFT={metrics['lift']*100:+5.1f}pp  "
        f"CI=[{metrics['lift_ci95_lo']*100:+.1f},{metrics['lift_ci95_hi']*100:+.1f}]pp  "
        f"|  Fisher p={p1:.4g} {sig}"
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    p.add_argument("--velocity-window-sec", type=float, default=3.0)
    p.add_argument("--adverse-window-sec", type=float, default=60.0)
    p.add_argument("--adverse-bps", type=float, default=2.0)
    p.add_argument("--velocity-threshold-quantile", type=float, default=0.75)
    p.add_argument("--sweep", action="store_true", help="run a parameter grid")
    args = p.parse_args()

    trade = pl.read_parquet(args.run_dir / "parquet" / "trade.parquet").sort("server_ts_ms")
    print(f"trade events: {trade.height}")
    print(f"side breakdown: {trade.group_by('side').agg(pl.len().alias('n'))}")
    print()

    if args.sweep:
        grid_v = [1.0, 3.0, 5.0, 10.0, 30.0]
        grid_a = [10.0, 30.0, 60.0, 180.0]
        grid_bps = [1.0, 2.0, 5.0, 10.0]
        grid_q = [0.50, 0.75, 0.90]
        results = []
        print("=== SWEEP (legend: * p<.05, ** p<.01, *** p<.001) ===")
        total = len(grid_v) * len(grid_a) * len(grid_bps) * len(grid_q)
        i = 0
        for vw in grid_v:
            for aw in grid_a:
                for bp in grid_bps:
                    for q in grid_q:
                        i += 1
                        params = {
                            "velocity_window_sec": vw, "adverse_window_sec": aw,
                            "adverse_bps": bp, "threshold_quantile": q,
                        }
                        m = evaluate(trade, **params)
                        if "error" in m:
                            continue
                        m.update(params)
                        results.append(m)
                        # print all with significance
                        print(fmt(m, params))
        # Sort and write
        results.sort(key=lambda r: r["fisher_one_sided_p"])
        out = args.run_dir / "h1_public_sweep.json"
        out.write_text(json.dumps(results, indent=2))
        print()
        print("=== TOP 10 by Fisher one-sided p (lowest = strongest evidence) ===")
        for r in results[:10]:
            params = {k: r[k] for k in ("velocity_window_sec", "adverse_window_sec", "adverse_bps", "threshold_quantile")}
            print(fmt(r, params))
        print(f"\nFull sweep saved: {out}")

    else:
        params = {
            "velocity_window_sec": args.velocity_window_sec,
            "adverse_window_sec": args.adverse_window_sec,
            "adverse_bps": args.adverse_bps,
            "threshold_quantile": args.velocity_threshold_quantile,
        }
        m = evaluate(trade, **params)
        print(fmt(m, params))
        print()
        print("=== Confusion ===")
        print(f"                signal_active  signal_inactive")
        print(f"  was_adverse        {m['tp']:>5d}        {m['fn']:>5d}    (n_adv={m['n_adverse']})")
        print(f"  not_adverse        {m['fp']:>5d}        {m['tn']:>5d}    (n_non={m['n_total']-m['n_adverse']})")
        print()
        print(f"  Fisher exact one-sided p (filter > random): {m['fisher_one_sided_p']:.6g}")
        print(f"  Fisher exact two-sided p:                    {m['fisher_two_sided_p']:.6g}")
        print(f"  Chi-square (Yates) p:                        {m['chi2_p']:.6g}")
        print(f"  Bootstrap 95% CI on LIFT:                    [{m['lift_ci95_lo']*100:+.2f}, {m['lift_ci95_hi']*100:+.2f}] pp")
        print(f"  Contains 0?: {m['lift_ci95_lo'] <= 0 <= m['lift_ci95_hi']}")
        out = args.run_dir / "h1_public_summary.json"
        out.write_text(json.dumps({**m, **params}, indent=2))
        print(f"\n  Summary saved: {out}")


if __name__ == "__main__":
    main()
