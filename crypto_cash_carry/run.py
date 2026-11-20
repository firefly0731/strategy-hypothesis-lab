"""Cash-and-carry backtests and the report (DESIGN.md §4–6).

    python -m crypto_cash_carry.run                       # fixed BTC+ETH, greedy spec, greedy improved
    python -m crypto_cash_carry.run --only fixed
    python -m crypto_cash_carry.run --no-tbill            # skip DTB3 (stated in the report)
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_dirty_carry.data import binance_archive_symbols, non_coin_symbols

from .data import build, dtb3, perp_to_spot, spot_archive_symbols
from .engine import Band, Costs, simulate
from .metrics import VIDEO_YEARLY, decomposition, performance, tbill_yearly, yearly
from .strategies import GreedyRule, fixed_targets, greedy_targets

OUT = Path(__file__).resolve().parent / "reports"
START, END = "2019-11-27", "2026-10-18"
FIXED_ENTRY = "2019-11-28 00:00"
UNMODELLED = """## Not modelled

- **Exchange counterparty risk.** All capital sits on one venue. An insolvency, default or withdrawal freeze (for example FTX in November 2022) can wipe out the whole book, and no backtest shows that risk.
- **Taxes and record keeping.** The book generates thousands of 8-hour funding cashflows per year. How each is taxed depends on the jurisdiction, and every one has to be recorded.
- **Operational assumptions.** Transfers between the spot and futures wallets are assumed instant and free. Funding uses the 1h perp close instead of the mark price. Market impact is assumed to stay within 2 bp slippage per side.
"""


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_fixed(costs, band):
    b = build(["BTCUSDT", "ETHUSDT"], START, END)
    m = b.market
    tg = fixed_targets(m.index, m.symbols, FIXED_ENTRY)
    r = simulate(m, tg, slots=2, costs=costs, band=band, close_at_end=True)
    j0 = m.index.get_loc(pd.Timestamp(FIXED_ENTRY, tz="UTC"))
    basis = np.abs(m.perp[j0:] / m.spot[j0:] - 1)
    wick = b.last_high[j0 + 1:] / m.perp[j0:-1] - 1
    jump = m.liq_high[j0 + 1:] / m.perp[j0:-1] - 1
    extra = {"settlements": int(b.n_settlements.sum()), "neg_funding_share": b.neg_settlements.sum() / b.n_settlements.sum(),
             "max_basis_gap": float(np.nanmax(basis)), "max_1h_mark_high_over_close": float(np.nanmax(jump)),
             "max_1h_last_high_over_close": float(np.nanmax(wick)),
             "liq_proxy_bars": {s: int(v) for s, v in zip(m.symbols, b.liq_proxy_bars)},
             "missing_bars": {s: int(np.isnan(m.spot[j0:, i]).sum() + np.isnan(m.perp[j0:, i]).sum())
                              for i, s in enumerate(m.symbols)}}
    return r, extra, None


def greedy_universe():
    drop = non_coin_symbols()
    spot = set(spot_archive_symbols("USDT"))
    perps = [p for p in binance_archive_symbols("USDT") if p not in drop and perp_to_spot(p)[0] in spot]
    return perps, spot


def run_greedy(costs, band, rule, bundle):
    tg, dlog = greedy_targets(bundle, rule)
    r = simulate(bundle.market, tg, slots=rule.k, costs=costs, band=band, close_at_end=True)
    return r, {"n_names_ever_held": int(r.by_symbol.shape[0]),
               "mean_names_held": float(r.bars["n_active"][r.bars["n_active"] > 0].mean())}, dlog


def table(d: dict, fmt="{:.4f}") -> str:
    return "\n".join(f"| {k} | {fmt.format(v) if isinstance(v, (float, np.floating)) else v} |" for k, v in d.items())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=["fixed", "greedy", "greedy_plus"])
    ap.add_argument("--no-tbill", action="store_true")
    a = ap.parse_args(argv)
    which = a.only or ["fixed", "greedy", "greedy_plus"]
    costs, band = Costs(), Band()
    OUT.mkdir(parents=True, exist_ok=True)
    runs = {}
    if "fixed" in which:
        log("fixed BTC+ETH: loading")
        runs["fixed"] = run_fixed(costs, band)
        log("fixed done")
    if {"greedy", "greedy_plus"} & set(which):
        perps, spot = greedy_universe()
        log(f"greedy universe: {len(perps)} USDT perps with a spot pair in the archive; loading")
        bundle = build(perps, START, END, spot_listed=spot)
        log(f"loaded {len(bundle.market.symbols)} names with both legs")
        if "greedy" in which:
            runs["greedy"] = run_greedy(costs, band, GreedyRule.spec(), bundle)
            log("greedy spec done")
        if "greedy_plus" in which:
            runs["greedy_plus"] = run_greedy(costs, band, GreedyRule.improved(costs, band), bundle)
            log("greedy improved done")
        del bundle

    tb = None if a.no_tbill else dtb3()
    lines = ["# Cash-and-carry backtest report", "",
             f"Window {START} .. {END} (inclusive), Binance spot + USDⓈ-M perps, 1h bars. "
             f"Costs: spot {costs.spot_fee:.2%}, perp {costs.perp_fee:.2%}, slippage {costs.slippage:.2%}/side. "
             f"Sleeve: {band.spot_frac:.0%} spot, {1 - band.spot_frac:.0%} margin, {band.target:.0f}x short, "
             f"band [{band.lo:.0f}x, {band.hi:.0f}x]. See DESIGN.md for every formula.", ""]
    summary, years = {}, {}
    for name, (r, extra, dlog) in runs.items():
        perf = performance(r.bars)
        dec = decomposition(r.bars)
        y = yearly(r.bars)
        if tb is not None:
            y = y.join(tbill_yearly(tb, y))
        years[name] = y
        summary[name] = {**perf, **{f"pnl_{k}": v for k, v in dec.items()}, **r.stats,
                         **{k: v for k, v in extra.items() if not isinstance(v, dict)}}
        r.bars.to_parquet(OUT / f"bars_{name}.parquet")
        r.trades.to_csv(OUT / f"trades_{name}.csv", index=False)
        r.by_symbol.sort_values("funding", ascending=False).to_csv(OUT / f"by_symbol_{name}.csv")
        y.to_csv(OUT / f"yearly_{name}.csv")
        if dlog is not None:
            dlog.to_csv(OUT / f"decisions_{name}.csv", index=False)
        for k, v in extra.items():
            if isinstance(v, dict):
                summary[name][k] = str(v)
    s = pd.DataFrame(summary)
    s.to_csv(OUT / "summary.csv")
    lines += ["## Overall", "", s.to_markdown(floatfmt=".4f"), ""]
    lines += ["PnL rows are in units of initial capital (1.0). They sum to the total return, which is asserted.", ""]
    for name, y in years.items():
        cols = ["return", "funding", "basis", "costs", "mdd"] + (["tbill_avg_pct", "tbill_return"] if tb is not None else [])
        t = y[cols].copy()
        if name == "fixed":
            t["video"] = pd.Series(VIDEO_YEARLY)
        lines += [f"## Yearly: {name}", "", t.to_markdown(floatfmt=".4f"), ""]
    if tb is not None and years:
        comp = pd.DataFrame({k: v["return"] for k, v in years.items()})
        comp["tbill_return"] = next(iter(years.values()))["tbill_return"]
        lines += ["## Comparison (yearly return)", "", comp.to_markdown(floatfmt=".4f"), ""]
    else:
        lines += ["T-bill comparison skipped (--no-tbill).", ""]
    lines += [UNMODELLED]
    (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    pd.set_option("display.width", 220)
    print(s.to_string())
    for name, y in years.items():
        print(f"\n{name}\n", y.drop(columns=["from", "to"]).round(4).to_string())
    log(f"report: {OUT / 'summary.md'}")


if __name__ == "__main__":
    main()
