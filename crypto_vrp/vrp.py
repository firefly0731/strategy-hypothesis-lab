"""Bitcoin / Ether variance risk premium: measurement and a short-volatility proxy.

Literature: Carr & Wu (2009) variance swaps. Almeida, Grith, Miftachov & Wang (2025,
arXiv 2410.15195) document a large Bitcoin VRP that is higher in the low-volatility
regime, which makes short volatility the canonical range-market strategy.

Two estimators (RESEARCH_PROTOCOL.md, numerical hygiene):
  1. ex-post 30-day variance swap: VRP_t = IV_t^2 - RV^2(t -> t+30d)
  2. daily gamma/theta P&L of a delta-hedged short straddle (ignores vega P&L):
        pnl_{t+1} = IV_t^2 / 365 - rv_{t+1}
     where rv_{t+1} is next day's realised variance (daily return^2, or the sum of 5-min r^2).
IV_t is DVOL at 00:00 UTC of day t, which is known when the position is set. Costs are a haircut of
c vol points on IV, a proxy for the option bid-ask spread and fees.

    python -m crypto_vrp.vrp
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_intraday_momentum.data import load_klines
from crypto_intraday_momentum.sizing import metrics
from .dvol import fetch_dvol

DAYS = 365


def daily_realised(sym: str, start="2021-03", end="2026-11") -> pd.DataFrame:
    df = load_klines(sym, start, end)
    c = df["close"]
    d = c.index.floor("D")
    r1 = np.log(c.resample("1D").last()).diff()                  # close-to-close (00:00 UTC)
    c5 = c.resample("5min").last()
    r5 = np.log(c5).diff()
    rv5 = (r5 ** 2).groupby(r5.index.floor("D")).sum(min_count=200)
    c30 = c.resample("30min").last()
    r30 = np.log(c30).diff()
    eff = r30.groupby(r30.index.floor("D")).apply(lambda x: abs(x.sum()) / x.abs().sum() if x.abs().sum() > 0 else np.nan)
    out = pd.DataFrame({"r": r1, "rv_d": r1 ** 2, "rv_5m": rv5, "eff": eff})
    out.index = out.index.tz_convert(None)
    # label D = the day the return covers: close(end of D) / close(end of D-1)
    return out


def build(cur: str, sym: str) -> pd.DataFrame:
    # Deribit candles are stamped at their START and "close" is the value one hour later.
    # The value known at 00:00 UTC is the OPEN of the 00:00 candle (using its close would peek 1h ahead).
    dv = fetch_dvol(cur)["open"]
    iv = dv[dv.index.hour == 0]
    iv.index = iv.index.tz_convert(None).normalize()
    rv = daily_realised(sym)
    # resample("1D").last() labels day D with the close at the end of day D
    X = pd.DataFrame({"iv": iv / 100}).join(rv, how="inner")
    # day D's IV (at 00:00 D) is set before day D's return -> pnl for day D uses iv(D) and rv(D)
    return X.dropna(subset=["iv"])


def nw_t(x: pd.Series, lags: int) -> float:
    x = x.dropna().to_numpy()
    T = len(x)
    e = x - x.mean()
    s = (e ** 2).sum() / T
    for l in range(1, lags + 1):
        s += 2 * (1 - l / (lags + 1)) * (e[l:] * e[:-l]).sum() / T
    return x.mean() / np.sqrt(s / T)


def analyse(name: str, X: pd.DataFrame, lines: list):
    def show(t, o):
        s = f"\n### {name}: {t}\n{o if isinstance(o, str) else o.round(4).to_string()}"
        print(s, flush=True); lines.append(s)

    iv2 = X["iv"] ** 2
    # 1) ex-post 30-day variance swap (entered at 00:00 of day t, covers days t..t+29)
    rv30_d = X["rv_d"][::-1].rolling(30, min_periods=30).sum()[::-1] * DAYS / 30
    rv30_5 = X["rv_5m"][::-1].rolling(30, min_periods=30).sum()[::-1] * DAYS / 30
    vrp_d, vrp_5 = iv2 - rv30_d, iv2 - rv30_5
    tab = pd.DataFrame({
        "mean_IV": [X["iv"].mean()], "mean_RV30 (daily r)": [np.sqrt(rv30_d).mean()],
        "mean_RV30 (5m)": [np.sqrt(rv30_5).mean()],
        "VRP var (daily)": [vrp_d.mean()], "NW t": [nw_t(vrp_d, 30)],
        "VRP var (5m)": [vrp_5.mean()], "NW t (5m)": [nw_t(vrp_5, 30)],
        "IV-RV vol pts (5m)": [(X["iv"] - np.sqrt(rv30_5)).mean() * 100],
        "% entries VRP>0 (5m)": [(vrp_5 > 0).mean() * 100],
    })
    show("ex-post 30d variance swap (two realised-variance estimators)", tab.T)
    yr = pd.DataFrame({"IV": X["iv"].groupby(X.index.year).mean() * 100,
                       "RV30_5m": np.sqrt(rv30_5).groupby(X.index.year).mean() * 100,
                       "VRP_var_5m": vrp_5.groupby(X.index.year).mean(),
                       "share>0": (vrp_5 > 0).groupby(X.index.year).mean() * 100})
    show("by year", yr)
    # regime: ex-ante trailing 30d realised vol terciles (Almeida et al.: VRP higher in low-vol regime)
    trail = np.sqrt(X["rv_5m"].rolling(30).sum().shift(1) * DAYS / 30)
    q = pd.qcut(trail, 3, labels=["low vol", "mid vol", "high vol"])
    show("VRP by ex-ante vol regime (5m)", pd.DataFrame({
        "VRP_var": vrp_5.groupby(q, observed=True).mean(),
        "IV-RV vol pts": (X["iv"] - np.sqrt(rv30_5)).groupby(q, observed=True).mean() * 100,
        "share>0": (vrp_5 > 0).groupby(q, observed=True).mean() * 100}))

    # 2) daily short-gamma P&L proxy, per unit of variance notional, scaled by 1/IV^2 (constant vega-ish)
    out = {}
    for hedge, rv in (("daily hedge", X["rv_d"]), ("5m hedge", X["rv_5m"])):
        for c in (0, 1, 2, 3):
            ive = (X["iv"] - c / 100).clip(lower=0.05)
            pnl = (ive ** 2 / DAYS - rv) / (X["iv"] ** 2 / DAYS)       # in units of one day's theta
            out[f"{hedge} | cost {c} vp"] = pnl
    S = pd.DataFrame(out).dropna()
    stats = {}
    for k, v in S.items():
        # scale to 20% annual vol ex-ante (trailing 60d vol of the series) for MDD comparability
        sc = 0.20 / (v.rolling(60, min_periods=30).std().shift(1) * np.sqrt(DAYS))
        y = (v * sc).dropna()
        m = metrics(y, DAYS)
        stats[k] = dict(sharpe=v.mean() / v.std() * np.sqrt(DAYS), t=v.mean() / v.std() * np.sqrt(len(v)),
                        skew=v.skew(), worst_day_theta=v.min(), mdd_at20vol=m["mdd"], cagr_at20vol=m["cagr"])
    show("daily short-gamma proxy (P&L in units of daily theta)", pd.DataFrame(stats).T)
    base = S["5m hedge | cost 1 vp"]
    show("short-gamma proxy (5m hedge, 1 vp cost) Sharpe by year",
         base.groupby(base.index.year).apply(lambda x: x.mean() / x.std() * np.sqrt(DAYS)).to_frame("sharpe"))
    eq = pd.qcut(X["eff"], 3, labels=["range day", "mid", "trend day"])
    show("short-gamma P&L by day type (efficiency ratio, ex-post, descriptive)",
         base.groupby(eq.reindex(base.index), observed=True).agg(["mean", "count"]))
    return S


def combine_with_momentum(S_btc: pd.Series, S_eth: pd.Series, lines: list):
    mom = pd.read_parquet("crypto_intraday_momentum/results/walkforward/oos_curves.parquet")["final config"]
    mom.index = pd.DatetimeIndex(mom.index).normalize()
    v = ((S_btc + S_eth) / 2).dropna()
    # vol-normalise the VRP series ex-ante to 20%/yr, then cumulate onto momentum session dates
    sc = 0.20 / (v.rolling(60, min_periods=30).std().shift(1) * np.sqrt(DAYS))
    vr = (v * sc).dropna()
    cum = (1 + vr).cumprod()
    cum_s = cum.reindex(cum.index.union(mom.index)).ffill().reindex(mom.index)
    vr_s = cum_s.pct_change()
    df = pd.DataFrame({"momentum": mom, "short_vol": vr_s}).dropna()
    df = df[df.index >= "2022-01-01"]
    corr = df.corr().iloc[0, 1]
    iv = 1 / df.rolling(60, min_periods=30).std().shift(1)
    w = iv.div(iv.sum(1), axis=0).fillna(0.5)
    combos = {"momentum": df["momentum"], "short_vol": df["short_vol"],
              "50/50": df.mean(1), "inv-vol (ex-ante)": (w * df).sum(1)}
    tab = pd.DataFrame({k: metrics(x, 252) for k, x in combos.items()}).T[["sharpe", "cagr", "vol", "mdd", "calmar"]]
    yr = pd.DataFrame({k: x.groupby(x.index.year).apply(lambda z: z.mean() / z.std() * np.sqrt(252)) for k, x in combos.items()})
    s = (f"\n### combination with momentum (session dates, 2022-01..)\ncorrelation = {corr:.3f}\n"
         + tab.round(3).to_string() + "\n\nyearly Sharpe\n" + yr.round(2).to_string())
    # does short vol earn when momentum loses?
    q = pd.qcut(df["momentum"], 3, labels=["mom worst third", "mid", "mom best third"])
    s += "\n\nshort-vol mean return by momentum-day tercile (bps)\n" + (df["short_vol"].groupby(q, observed=True).mean() * 1e4).round(2).to_string()
    print(s); lines.append(s)


def main():
    lines = []
    out = {}
    for cur, sym in (("BTC", "BTCUSDT"), ("ETH", "ETHUSDT")):
        X = build(cur, sym)
        out[cur] = analyse(cur, X, lines)
    combine_with_momentum(out["BTC"]["5m hedge | cost 1 vp"], out["ETH"]["5m hedge | cost 1 vp"], lines)
    import pathlib
    p = pathlib.Path("crypto_vrp/results"); p.mkdir(parents=True, exist_ok=True)
    (p / "report.txt").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
