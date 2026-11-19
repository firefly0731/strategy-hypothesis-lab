"""Run the noise-band intraday momentum backtest on Binance USDT-M futures.

    python -m crypto_intraday_momentum.run --symbols BTCUSDT ETHUSDT --session us
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .backtest import Config, run_backtest
from .data import load_funding, load_klines
from .report import random_direction_test, summarize, yearly
from .sessions import SPECS, build_sessions
from .signals import compute_signals

# Price tick sizes of the USDT-M perpetuals (check exchangeInfo before live use).
TICKS = {"BTCUSDT": 0.1, "ETHUSDT": 0.01, "SOLUSDT": 0.01, "BNBUSDT": 0.01,
         "XRPUSDT": 0.0001, "DOGEUSDT": 0.00001}

VARIANTS = {
    "taker":            dict(entry_mode="taker", exit_mode="taker"),
    "maker_skip":       dict(entry_mode="maker", entry_fallback="skip", exit_mode="maker"),
    "maker_chase":      dict(entry_mode="maker", entry_fallback="taker", exit_mode="maker"),
    "maker_in_taker_out": dict(entry_mode="maker", entry_fallback="skip", exit_mode="taker"),
}
PPY = {"us": 252, "utc": 365}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--session", choices=list(SPECS), nargs="+", default=["us", "utc"])
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument("--lookback", type=int, default=14)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--sizing", default="vol", choices=["vol", "fixed"])
    ap.add_argument("--out", default=str(Path(__file__).parent / "results"))
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, years = [], []
    for sym in a.symbols:
        df = load_klines(sym, a.start, a.end)
        fund = load_funding(sym, a.start, a.end)
        for sess in a.session:
            m = build_sessions(df, SPECS[sess])
            sig = compute_signals(m, lookback=a.lookback, interval=a.interval)
            for v in a.variants:
                cfg = Config(tick=TICKS.get(sym, 0.01), sizing=a.sizing, **VARIANTS[v])
                res = run_backtest(m, sig, cfg, fund)
                st = summarize(res, PPY[sess])
                if v == "taker":
                    st.update({f"rand_{k}": x for k, x in random_direction_test(res).items()})
                rows.append(dict(symbol=sym, session=sess, variant=v, **st))
                y = yearly(res).reset_index()
                y.insert(0, "variant", v); y.insert(0, "session", sess); y.insert(0, "symbol", sym)
                years.append(y)
                res.trades.to_csv(out / f"trades_{sym}_{sess}_{v}.csv", index=False)
                print(json.dumps(rows[-1], default=str), flush=True)

    summary = pd.DataFrame(rows)
    summary.to_csv(out / "summary.csv", index=False)
    pd.concat(years).to_csv(out / "yearly.csv", index=False)
    return summary


if __name__ == "__main__":
    main()
