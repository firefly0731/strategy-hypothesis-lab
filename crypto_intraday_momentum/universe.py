"""Universe expansion with monthly point-in-time selection.

Survivorship control: the candidate list includes coins that later collapsed or
were delisted (LUNA, FTT, MATIC). A coin can only be picked in month M if it had
enough history and liquidity BEFORE month M. Every selection statistic uses only
sessions before the month starts.

Per symbol (adopted rules, maker_chase with a 1 bp maker offset for every coin):
  u       : unit-notional strategy session return (for trailing strategy stats)
  r       : rv24-sized session return (uncapped leverage, before portfolio scaling)
  qv      : US-session quote volume (USD)
  vr_*    : pieces of a variance ratio (session move vs 13 x 30-min moves)

    python -m crypto_intraday_momentum.universe
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Config
from .cpcv import EXEC, run_cpcv
from .data import load_funding, load_klines
from .sessions import US, build_sessions
from .signals import compute_signals
from .sizing import apply_scheme, drawdown_throttle, metrics, pre_open_rv, unit_trades

OUT = Path(__file__).parent / "results" / "universe"
PPY = 252
ADOPTED = dict(entry_cutoff_min=270, vwap_confirm_k=0.6, maker_offset_bps=1.0)
CANDIDATES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
              "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "TRXUSDT",
              "MATICUSDT", "ATOMUSDT", "NEARUSDT", "FILUSDT", "ETCUSDT", "UNIUSDT", "AAVEUSDT",
              "OPUSDT", "ARBUSDT", "APTUSDT", "SUIUSDT", "1000PEPEUSDT", "FTTUSDT", "LUNAUSDT"]
FIXED3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
SEEN = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"}   # used in earlier analysis


def prep_symbol(sym: str, start: str, end: str, exec_name: str = "maker_chase") -> pd.DataFrame | None:
    try:
        df = load_klines(sym, start, end)
    except ValueError:
        return None
    fund = load_funding(sym, start, end)
    m = build_sessions(df, US, quality_lookback=30)
    if m.n < 60:
        return None
    s = compute_signals(m)
    t = unit_trades(m, s, Config(**EXEC[exec_name], **ADOPTED), fund)
    rv = pre_open_rv(df, m)
    n = m.n
    u = np.zeros(n)
    if len(t):
        np.add.at(u, t["sess_idx"].to_numpy(), t["ret_notional"].to_numpy())
        res = apply_scheme(t, m, "rv24", cap=1e9, rv24=rv)
        r = res.sess_ret.to_numpy()
        maxlev = np.zeros(n)
        np.maximum.at(maxlev, t["sess_idx"].to_numpy(), res.lev.to_numpy())
    else:
        r, maxlev = np.zeros(n), np.zeros(n)
    c30 = m.C[:, 29::30]
    prev = np.concatenate([m.O[:, :1], c30[:, :-1]], axis=1)
    r30 = np.log(c30 / prev)
    out = pd.DataFrame({
        "u": u, "r": r, "maxlev": maxlev,
        "qv": m.QV.sum(axis=1),
        "vr_num": np.log(m.C[:, -1] / m.O[:, 0]) ** 2,
        "vr_den": (r30 ** 2).sum(axis=1),
        "tradable": m.tradable,
    }, index=m.dates)
    out.index.name = "date"
    return out


def _trailing(panel: dict[str, pd.DataFrame], col: str, window: int, fn) -> pd.DataFrame:
    X = pd.DataFrame({s: d[col] for s, d in panel.items()})
    return fn(X.rolling(window, min_periods=window)).shift(1)      # strictly prior sessions


def selection_masks(panel, min_hist=250, min_qv=100e6, k_list=(3, 5, 8)) -> dict[str, pd.DataFrame]:
    """Month-start selections, held for the whole month. Returns {variant: 0/1 mask}."""
    U = pd.DataFrame({s: d["u"] for s, d in panel.items()})
    dates = U.index
    hist = U.notna().cumsum().shift(1).fillna(0)
    qv = _trailing(panel, "qv", 30, lambda r: r.median())
    sr = _trailing(panel, "u", min_hist, lambda r: r.mean() / r.std())
    vnum = _trailing(panel, "vr_num", 120, lambda r: r.mean())
    vden = _trailing(panel, "vr_den", 120, lambda r: r.mean())
    vr = vnum / vden
    month = pd.Series(dates.to_period("M"), index=dates)
    first = month.ne(month.shift())                     # first session of each month
    elig = (hist >= min_hist) & (qv >= min_qv)
    masks = {}

    def hold(mask_at_first):
        m = mask_at_first.where(first, np.nan).ffill().fillna(0)
        return m.astype(float)

    masks["fixed_BTC_ETH_SOL"] = pd.DataFrame(0.0, index=dates, columns=U.columns).assign(
        **{s: 1.0 for s in FIXED3 if s in U.columns}).where(U.notna(), 0.0)
    masks["all_liquid"] = hold(elig.astype(float))
    masks["liquid_sr>0"] = hold((elig & (sr > 0)).astype(float))
    masks["liquid_vr>1"] = hold((elig & (vr > 1)).astype(float))
    for k in k_list:
        rank = sr.where(elig).rank(axis=1, ascending=False)
        masks[f"top{k}_by_trailing_sr"] = hold((rank <= k).astype(float))
    return masks


def portfolio(panel, mask: pd.DataFrame, target=0.25, scale_cap=20.0, dd=0.15, vol_lb=60):
    R = pd.DataFrame({s: d["r"] for s, d in panel.items()}).reindex(mask.index).fillna(0.0)
    L = pd.DataFrame({s: d["maxlev"] for s, d in panel.items()}).reindex(mask.index).fillna(0.0)
    k = mask.sum(axis=1).replace(0, np.nan)
    W = mask.div(k, axis=0).fillna(0.0)
    raw = (W * R).sum(axis=1)
    vol = raw.rolling(vol_lb, min_periods=20).std().shift(1) * np.sqrt(PPY)
    scale = (target / vol).clip(upper=scale_cap).fillna(0.0)
    out = raw * scale
    eff = (W * L).mul(scale, axis=0)
    if dd is not None:
        out, _ = drawdown_throttle(out, dd)
    return out, raw, eff, mask.sum(axis=1)


def _sr(x):
    return x.mean() / x.std(ddof=1) * np.sqrt(PPY)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-11")
    ap.add_argument("--eval-start", default="2022-01-01", help="first session counted in results")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    n = len(CANDIDATES)
    with ProcessPoolExecutor(3) as ex:
        res = list(ex.map(prep_symbol, CANDIDATES, [a.start] * n, [a.end] * n))
    panel = {s: d for s, d in zip(CANDIDATES, res) if d is not None}
    dates = sorted(set().union(*[d.index for d in panel.values()]))
    panel = {s: d.reindex(dates) for s, d in panel.items()}
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    lines = []

    def show(title, obj):
        txt = f"\n### {title}\n{obj if isinstance(obj, str) else obj.round(3).to_string()}"
        print(txt, flush=True); lines.append(txt)

    ev = pd.Timestamp(a.eval_start)
    # 1) the adopted rules on every coin (new coins = fresh out-of-sample test of the rules)
    rows = []
    for s, d in panel.items():
        x = d.loc[d.index >= ev, "u"].dropna()
        if len(x) < 100:
            continue
        rows.append(dict(symbol=s, seen_before=s in SEEN, sessions=len(x), first=x.index[0].date(),
                         last=x.index[-1].date(), sharpe=_sr(x), t=x.mean() / x.std(ddof=1) * np.sqrt(len(x)),
                         med_qv_musd=d["qv"].median() / 1e6))
    per = pd.DataFrame(rows).sort_values("sharpe", ascending=False).set_index("symbol")
    show("adopted rules per coin (unit notional, 2022-01 .. 2026-11)", per)
    new = per[~per.seen_before]
    show("coins NOT used in any earlier analysis",
         f"n={len(new)}  positive Sharpe: {(new.sharpe > 0).sum()}  median Sharpe={new.sharpe.median():.2f}  "
         f"mean t={new.t.mean():.2f}")
    U = pd.DataFrame({s: d["u"] for s, d in panel.items()})
    C = U[U.index >= ev].corr(min_periods=200)
    show("average pairwise correlation of strategy returns",
         f"{np.nanmean(C.where(~np.eye(len(C), dtype=bool)).to_numpy()):.3f}")

    # 2) universe variants
    masks = selection_masks(panel)
    S, rows = {}, []
    for name, mk in masks.items():
        out, raw, eff, k = portfolio(panel, mk)
        out, raw = out[out.index >= ev], raw[raw.index >= ev]
        S[name] = out
        mt = metrics(out)
        rows.append(dict(variant=name, avg_coins=k[k.index >= ev].mean(), **mt,
                         raw_sharpe=_sr(raw), p99_eff_lev=np.nanquantile(eff[eff.index >= ev].to_numpy()[eff[eff.index >= ev].to_numpy() > 0], 0.99)))
    tab = pd.DataFrame(rows).set_index("variant").sort_values("sharpe", ascending=False)
    show("universe variants (rv24 sizing, 25% vol target, dd throttle 15%)", tab)
    S = pd.DataFrame(S)
    show("yearly Sharpe", S.groupby(S.index.year).apply(lambda x: x.apply(_sr)).T)
    cv = run_cpcv(S, 10, 2, 30)
    psr = cv.paths.apply(_sr)
    show("CPCV over universe variants",
         f"PBO={cv.pbo:.2f}  OOS path SR mean={psr.mean():.2f} min={psr.min():.2f}\nchosen: "
         + ", ".join(f"{k}({v})" for k, v in cv.chosen.combo.value_counts().items()))
    best = tab.index[0]
    held = masks[best]
    freq = held[held.index >= ev].mean().sort_values(ascending=False)
    show(f"share of sessions each coin was held in '{best}'", freq[freq > 0].to_frame("share"))
    S.to_parquet(OUT / "variant_returns.parquet")
    per.to_csv(OUT / "per_coin.csv")
    (OUT / "report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
