"""Run the dirty carry backtest on Binance USDⓈ-M perpetuals (raw vs factor-neutral, same schedule).

    python -m crypto_dirty_carry.run --quote USDC --start 2024-01 --end 2026-10
    python -m crypto_dirty_carry.run --quote USDT --start 2021-01 --end 2026-10

The universe is every perpetual with that quote asset in /fapi/v1/exchangeInfo (current listing;
contracts delisted earlier are missing → survivorship bias, reported in the output).
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from .backtest import compute_schedule, run_backtest
from .config import CostConfig, StrategyConfig
from .data import binance_archive_symbols, binance_universe, from_binance, non_coin_symbols

OUT = Path(__file__).resolve().parent / "results"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quote", default="USDC", choices=["USDC", "USDT"])
    ap.add_argument("--start", default="2024-01")
    ap.add_argument("--end", default=pd.Timestamp.now(tz="UTC").strftime("%Y-%m"))
    ap.add_argument("--bar", default="1h")
    ap.add_argument("--symbols", nargs="*", help="override the exchangeInfo universe")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--relative", action="store_true",
                    help="drop the sign conditions: short the top-k and long the bottom-k carry")
    ap.add_argument("--mode", default="projection", choices=["projection", "hedge"])
    ap.add_argument("--rebalance", default="8h", help="decision interval, e.g. 8h or 1D")
    ap.add_argument("--lookback", default="3D", help="funding carry lookback, e.g. 3D or 7D")
    ap.add_argument("--buffer", type=float, default=None, help="rank buffer multiple of k, e.g. 2")
    ap.add_argument("--universe", default="current", choices=["current", "archive"],
                    help="current: today's exchangeInfo (survivor bias); archive: every symbol with a "
                         "kline archive, delisted included, minus TradFi/index contracts (point in time)")
    ap.add_argument("--top-n", type=int, default=None, help="liquidity rank filter at each decision")
    ap.add_argument("--min-qv", type=float, default=0.0, help="min 30D median quote volume per bar")
    a = ap.parse_args(argv)

    if a.symbols:
        symbols = a.symbols
    elif a.universe == "archive":
        drop = non_coin_symbols()
        symbols = [s for s in binance_archive_symbols(a.quote) if s not in drop]
    else:
        symbols = list(binance_universe(a.quote)["symbol"])
    btc = f"BTC{a.quote}"
    data = from_binance(symbols, a.start, a.end, bar=a.bar, factor_map={"BTC": btc}, workers=16,
                        funding_min_qv=a.min_qv if a.min_qv > 0 else None)
    cfg = StrategyConfig(k=a.k, hedge_instruments=(btc,), costs=CostConfig.binance(a.quote),
                         neutral_mode=a.mode, rebalance_every=a.rebalance,
                         funding_lookback=a.lookback, buffer_mult=a.buffer,
                         liquidity_top_n=a.top_n, min_median_quote_volume=a.min_qv)
    if a.relative:
        cfg = replace(cfg, short_min_signal=None, long_max_signal=None)
    schedule = compute_schedule(data, cfg)
    runs = {"hedged": run_backtest(data, cfg, "hedged", schedule=schedule),
            "raw": run_backtest(data, cfg, "raw", schedule=schedule)}

    pd.set_option("display.width", 200)
    print(f"universe: {len(data.symbols)} {a.quote} perps with data, {data.close.index[0]} .. "
          f"{data.close.index[-1]}; exchangeInfo lists current/settling contracts only (survivorship bias)")
    print(pd.DataFrame({k: r.metrics for k, r in runs.items()}).round(4).to_string())
    print("\nPnL attribution (initial equity = 1):")
    print(pd.DataFrame({k: r.attribution for k, r in runs.items()}).round(4).to_string())
    print("\nex-ante BTC exposure per decision (mean, mean |.|):")
    ex = runs["hedged"].exposures
    print(ex[["BTC_raw", "BTC_hedged"]].agg(["mean", lambda x: x.abs().mean()]).round(4).to_string())
    print("\nex-post betas (daily):")
    for k, r in runs.items():
        print(k, "\n", r.betas.round(3).to_string())
    OUT.mkdir(parents=True, exist_ok=True)
    tag = f"{a.quote}_{a.start}_{a.end}_{a.bar}_{a.mode}{'_rel' if a.relative else ''}_rb{a.rebalance}_lb{a.lookback}_buf{a.buffer}_{a.universe}_top{a.top_n}"
    print("\ndecision status:", ex["status"].value_counts().to_dict())
    print("yearly net return:\n", runs["hedged"].bars["ret"].groupby(runs["hedged"].bars.index.year)
          .apply(lambda r: (1 + r).prod() - 1).round(4).to_string())
    for k, r in runs.items():
        r.bars.to_parquet(OUT / f"bars_{k}_{tag}.parquet")
    ex.to_parquet(OUT / f"exposures_{tag}.parquet")


if __name__ == "__main__":
    main()
