"""Compare position-sizing schemes and choose the portfolio leverage.

Pipeline (all causal):
  1. per symbol: 1x unit trades -> per-trade leverage from a sizing scheme
  2. portfolio: combine symbols (equal or inverse strategy-vol weights)
  3. portfolio vol target: scale_i = target / realised vol of the last 60
     sessions of the unscaled portfolio, capped
  4. per-trade effective leverage on total equity capped at `max_lev`
  5. optional drawdown throttle

    python -m crypto_intraday_momentum.run_sizing
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Config
from .cpcv import EXEC
from .data import load_funding, load_klines
from .run import TICKS
from .sessions import US, build_sessions
from .signals import compute_signals
from .sizing import apply_scheme, drawdown_throttle, metrics, pre_open_rv, unit_trades

OUT = Path(__file__).parent / "results" / "sizing"
PPY, WARMUP = 252, 31
SCHEMES = ["paper", "rv24", "ewma_rv24", "strategy_vol", "risk_per_trade"]
RULES = dict(entry_cutoff_min=270, vwap_confirm_k=0.6)


def load_symbol(sym, start, end, exec_name):
    df = load_klines(sym, start, end)
    fund = load_funding(sym, start, end)
    m = build_sessions(df, US)
    s = compute_signals(m)
    t = unit_trades(m, s, Config(tick=TICKS.get(sym, 0.01), **EXEC[exec_name], **RULES), fund)
    return m, t, pre_open_rv(df, m)


def build_portfolio(data, scheme, weighting, target_ann, max_lev, dd_max=None,
                    vol_lookback=60, scale_cap=20.0):
    per_sym_raw, trades = {}, {}
    for sym, (m, t, rv) in data.items():
        res = apply_scheme(t, m, scheme, cap=1e9, rv24=rv)      # caps applied at the end
        per_sym_raw[sym] = res.sess_ret
        trades[sym] = (m, t, res.lev.to_numpy())
    R = pd.DataFrame(per_sym_raw).fillna(0.0).iloc[WARMUP:]
    if weighting == "equal":
        W = pd.DataFrame(1.0 / R.shape[1], index=R.index, columns=R.columns)
    else:
        iv = 1.0 / R.rolling(60, min_periods=20).std().shift(1)
        W = iv.div(iv.sum(axis=1), axis=0).fillna(1.0 / R.shape[1])
    raw = (W * R).sum(axis=1)
    vol = raw.rolling(vol_lookback, min_periods=20).std().shift(1) * np.sqrt(PPY)
    scale = (target_ann / vol).clip(upper=scale_cap).fillna(0.0)    # 0 during warm-up
    # effective per-trade leverage on total equity, capped
    out = pd.Series(0.0, index=R.index)
    lev_rows = []
    for sym, (m, t, lev) in trades.items():
        d = pd.DatetimeIndex(m.dates[t["sess_idx"].to_numpy()])
        ok = d.isin(R.index)
        eff = np.zeros(len(t))
        eff[ok] = np.minimum(max_lev, lev[ok] * W[sym].reindex(d[ok]).to_numpy()
                             * scale.reindex(d[ok]).to_numpy())
        contrib = pd.Series(eff * t["ret_notional"].to_numpy(), index=d).groupby(level=0).sum()
        out = out.add(contrib.reindex(out.index).fillna(0.0))
        lev_rows.append(pd.DataFrame({"sym": sym, "eff": eff[ok], "mae": t["mae"].to_numpy()[ok]}))
    if dd_max is not None:
        out, _ = drawdown_throttle(out, dd_max)
    L = pd.concat(lev_rows)
    return out, L


def bootstrap_mdd(r: pd.Series, n: int = 2000, block: int = 20, seed: int = 0) -> np.ndarray:
    x = r.to_numpy()
    T = len(x)
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    nb = int(np.ceil(T / block))
    for k in range(n):
        st = rng.integers(0, T - block, nb)
        path = np.concatenate([x[s:s + block] for s in st])[:T]
        eq = np.cumprod(1 + path)
        out[k] = (eq / np.maximum.accumulate(eq) - 1).min()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--exec", default="maker_chase", choices=list(EXEC))
    ap.add_argument("--max-lev", type=float, default=3.0)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    data = {s: load_symbol(s, a.start, a.end, a.exec) for s in a.symbols}
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    lines = []

    def show(title, obj):
        txt = f"\n### {title}\n{obj if isinstance(obj, str) else obj.round(3).to_string()}"
        print(txt, flush=True); lines.append(txt)

    # adverse excursion: how far trades go against us before exit (for leverage limits)
    loss = pd.concat({s: -t["mae"] for s, (_, t, _) in data.items()})   # positive = adverse
    show("max adverse excursion per trade (loss fraction of entry price)",
         loss.groupby(level=0).quantile([0.5, 0.9, 0.99, 0.999, 1.0]).unstack())

    # 1) scheme comparison at a common ex-ante portfolio vol target (20%)
    rows, series = [], {}
    for sc in SCHEMES:
        for wt in ("equal", "inv_vol"):
            for dd in (None, 0.15):
                r, L = build_portfolio(data, sc, wt, 0.20, a.max_lev, dd)
                key = f"{sc}|{wt}|{'dd15' if dd else '-'}"
                series[key] = r
                mt = metrics(r.iloc[60:])
                rows.append(dict(scheme=sc, weights=wt, dd_throttle=bool(dd), **mt,
                                 avg_eff_lev=L["eff"].mean(), p99_eff_lev=L["eff"].quantile(.99)))
    tab = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    show("sizing schemes @ 20% ex-ante portfolio vol target (BTC+ETH+SOL)", tab.set_index(["scheme", "weights", "dd_throttle"]))
    S = pd.DataFrame(series).iloc[60:]
    yr = S.groupby(S.index.year).apply(lambda x: x.mean() / x.std(ddof=1) * np.sqrt(PPY)).T
    show("yearly Sharpe", yr.loc[tab.apply(lambda r: f"{r.scheme}|{r.weights}|{'dd15' if r.dd_throttle else '-'}", axis=1)].head(10))
    base = S["paper|equal|-"]
    diffs = {k: (S[k] - base).mean() / (S[k] - base).std(ddof=1) * np.sqrt(len(S)) for k in S if k != "paper|equal|-"}
    show("paired t-stat vs paper|equal (same vol target)", pd.Series(diffs).sort_values(ascending=False).to_frame("t"))

    # 2) leverage choice for the best scheme: MDD vs target vol (+ bootstrap MDD)
    best = tab.iloc[0]
    rows = []
    for tv in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        r, L = build_portfolio(data, best.scheme, best.weights, tv, a.max_lev,
                               0.15 if best.dd_throttle else None)
        r = r.iloc[60:]
        mt = metrics(r)
        b = bootstrap_mdd(r)
        rows.append(dict(target_vol=tv, **{k: mt[k] for k in ("sharpe", "cagr", "vol", "mdd", "calmar", "worst_day")},
                         boot_mdd_median=np.median(b), boot_mdd_p95=np.quantile(b, 0.05),
                         avg_eff_lev=L["eff"].mean(), max_eff_lev=L["eff"].max()))
    show(f"leverage ladder for {best.scheme}|{best.weights}|dd={best.dd_throttle}", pd.DataFrame(rows).set_index("target_vol"))
    rows = []
    for tv in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        r, L = build_portfolio(data, "paper", "equal", tv, a.max_lev)
        r = r.iloc[60:]
        mt = metrics(r)
        b = bootstrap_mdd(r)
        rows.append(dict(target_vol=tv, **{k: mt[k] for k in ("sharpe", "cagr", "vol", "mdd", "calmar")},
                         boot_mdd_median=np.median(b), boot_mdd_p95=np.quantile(b, 0.05),
                         avg_eff_lev=L["eff"].mean()))
    show("leverage ladder for paper|equal (reference)", pd.DataFrame(rows).set_index("target_vol"))
    S.to_parquet(OUT / "scheme_returns.parquet")
    (OUT / "report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
