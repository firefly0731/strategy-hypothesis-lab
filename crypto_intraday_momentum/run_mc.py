"""Compare paper sigma bands with Markov-chain Monte-Carlo bands.

    python -m crypto_intraday_momentum.run_mc
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Config, run_backtest
from .cpcv import EXEC, market_session_returns, regime_decomposition, run_cpcv
from .data import load_funding, load_klines
from .mc_bands import compute_mc_signals
from .report import summarize
from .run import TICKS
from .sessions import US, build_sessions
from .signals import compute_signals

OUT = Path(__file__).parent / "results" / "mc"
PPY = 252
WARMUP = 31
CONFIGS = [("paper_sigma", None)] + [
    (f"mc_s{ns}_q{q:g}", dict(n_states=ns, q=q)) for ns in (1, 3) for q in (0.70, 0.79, 0.85, 0.90)
]


def _one(sym, start, end, exec_name, lookback, n_paths):
    df = load_klines(sym, start, end)
    fund = load_funding(sym, start, end)
    m = build_sessions(df, US)
    base = compute_signals(m)
    cfg = Config(tick=TICKS.get(sym, 0.01), **EXEC[exec_name])
    rets, rows, trades = {}, [], {}
    for name, kw in CONFIGS:
        s = base if kw is None else compute_mc_signals(m, base=base, lookback=lookback,
                                                       n_paths=n_paths, **kw)
        res = run_backtest(m, s, cfg, fund)
        r = res.sessions["ret"].where(res.sessions["active"], 0.0).to_numpy()[WARMUP:]
        rets[name] = r
        st = summarize(res, PPY)
        rows.append(dict(symbol=sym, config=name, **{k: st.get(k) for k in (
            "trades", "total_return", "sharpe", "max_drawdown", "win_rate",
            "avg_gross_bps", "avg_bps_per_trade", "t_stat", "total_return_ex_top10_days")}))
    R = pd.DataFrame(rets, index=m.dates[WARMUP:])
    mk = market_session_returns(m, WARMUP)
    return sym, R, mk, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+",
                    default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"])
    ap.add_argument("--basket", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--exec", default="maker_chase", choices=list(EXEC))
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--paths", type=int, default=2000)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    n = len(a.symbols)
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(_one, a.symbols, [a.start] * n, [a.end] * n, [a.exec] * n,
                          [a.lookback] * n, [a.paths] * n))
    full = pd.DataFrame([r for *_, rows in res for r in rows])
    full.to_csv(OUT / "full_sample.csv", index=False)
    data = {s: (R, mk) for s, R, mk, _ in res}
    bk = [s for s in a.basket if s in data]
    if len(bk) > 1:
        idx = data[bk[0]][0].index
        for s in bk[1:]:
            idx = idx.intersection(data[s][0].index)
        data["BASKET"] = (sum(data[s][0].loc[idx] for s in bk) / len(bk),
                          sum(data[s][1].loc[idx] for s in bk) / len(bk))

    rows = []
    for name, (R, mk) in data.items():
        R.to_parquet(OUT / f"rets_{name}.parquet")
        cv = run_cpcv(R, 10, 2, 30)
        path_sr = cv.paths.apply(lambda x: x.mean() / x.std(ddof=1) * np.sqrt(PPY))
        for c in R.columns:
            d = regime_decomposition(R[c], mk, PPY)
            mt = d["move_table"]["mean_bps"]
            rows.append(dict(symbol=name, config=c, sharpe=d["raw_sharpe"], t=d["raw_t"],
                             mean_bps=d["raw_mean_bps"], beta_mkt_t=d["beta_mkt_t"],
                             quiet_bps=mt.get("quiet"), normal_bps=mt.get("normal"),
                             trend_bps=mt.get("trend")))
        rows.append(dict(symbol=name, config="CPCV_select", sharpe=path_sr.mean(),
                         t=np.nan, mean_bps=cv.paths.mean(axis=1).mean() * 1e4,
                         pbo=cv.pbo, path_sr_min=path_sr.min(),
                         chosen=", ".join(f"{k}({v})" for k, v in
                                          cv.chosen["combo"].value_counts().head(3).items())))
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "session_level.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(full.round(3).to_string(index=False))
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
