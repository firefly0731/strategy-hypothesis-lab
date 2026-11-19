"""Steps 4-6: market-neutral perp grid range-premium test, CPCV PBO, regimes,
complementarity with the intraday momentum strategy.

    python3 -m crypto_grid.run_neutral

Pre-registered (see README): grid k in {0.25%, 0.5%, 1%, 2%} x h in {3, 6, 10} = 12 combos,
primary = (k=1%, h=6). Discovery = BTC, ETH; hold-out = SOL, BNB, XRP, DOGE.
Selection rule: highest discovery-basket net Sharpe. Writes crypto_grid/results/neutral/.
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_intraday_momentum.cpcv import run_cpcv

from .data import load_funding_local, load_klines_local, ohlc_arrays
from .metrics import day_end_bars, nw_ols, sharpe, tstat
from .neutral import daily_pnl, run_neutral

OUT = Path(__file__).parent / "results" / "neutral"
START, END = "2021-01-01", "2026-11-17 23:59"
DISC = ["BTCUSDT", "ETHUSDT"]
HOLD = ["SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
KS = [0.0025, 0.005, 0.01, 0.02]
HS = [3, 6, 10]
COMBOS = [f"k{k:g}_h{h}" for k, h in product(KS, HS)]
PRIMARY = "k0.01_h6"
MOM = Path(__file__).resolve().parent.parent / "crypto_intraday_momentum" / "results" / "walkforward" / "oos_curves.parquet"


def run_symbol(sym: str) -> dict:
    df = load_klines_local(sym, START, END)
    o, hi, lo, cl = ohlc_arrays(df)
    idx = df.index
    last, days = day_end_bars(idx)
    fund = load_funding_local(sym, START, END)
    ft = pd.DatetimeIndex(fund["time"]) - pd.Timedelta(minutes=1)     # bar ending at the settlement
    fb = idx.searchsorted(ft)
    ok = (fb < len(idx)) & (fb >= 0)
    fb, fr = fb[ok], fund["rate"].to_numpy()[ok]
    out = {}
    for k, h in product(KS, HS):
        log = run_neutral(o, hi, lo, cl, k, h)
        d = daily_pnl(log, cl, last, fb, fr)
        name = f"k{k:g}_h{h}"
        for part in ("net", "gross", "fees", "funding"):
            out[(name, part)] = d[part]
        out[(name, "n_fills")] = log.n_fills
        out[(name, "n_stops")] = len(log.stops)
    # regime descriptors (ex post, description only)
    lr = np.diff(np.log(cl), prepend=np.log(o[0]))
    day_id = np.searchsorted(last, np.arange(len(cl)), side="left")
    rv = np.sqrt(np.bincount(day_id, weights=lr ** 2, minlength=len(last)))
    c30 = df["close"].resample("30min").last()
    r30 = np.log(c30).diff().fillna(np.log(c30.iloc[0] / o[0]))
    g = r30.groupby(r30.index.normalize().tz_localize(None))
    er = (g.sum().abs() / g.apply(lambda x: x.abs().sum())).reindex(days)
    ret_d = cl[last] / np.r_[o[0], cl[last][:-1]] - 1
    return dict(sym=sym, days=days, data=out, rv=rv, er=er.to_numpy(), ret=ret_d)


def mdd_additive(p: np.ndarray) -> float:
    cum = np.cumsum(p)
    return float(np.max(np.maximum.accumulate(np.r_[0.0, cum])[1:] - cum))


def stats(p: pd.Series) -> dict:
    x = p.to_numpy()
    return dict(ann_ret=x.mean() * 365, sharpe=sharpe(x), t=tstat(x), mdd=mdd_additive(x), n=len(x))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "raw.pkl"
    if raw.exists() and "--rerun" not in sys.argv:
        res = pd.read_pickle(raw)
    else:
        with ProcessPoolExecutor(3) as ex:
            res = {r["sym"]: r for r in ex.map(run_symbol, DISC + HOLD)}
        pd.to_pickle(res, raw)
    days = res["BTCUSDT"]["days"]
    for s in res:
        assert res[s]["days"].equals(days), s
    net = {s: pd.DataFrame({c: res[s]["data"][(c, "net")] for c in COMBOS}, index=days) for s in res}
    gross = {s: pd.DataFrame({c: res[s]["data"][(c, "gross")] for c in COMBOS}, index=days) for s in res}
    fees = {s: pd.DataFrame({c: res[s]["data"][(c, "fees")] for c in COMBOS}, index=days) for s in res}
    fund = {s: pd.DataFrame({c: res[s]["data"][(c, "funding")] for c in COMBOS}, index=days) for s in res}
    pd.concat({s: net[s] for s in res}, axis=1).to_parquet(OUT / "daily_net.parquet")
    pd.concat({s: gross[s] for s in res}, axis=1).to_parquet(OUT / "daily_gross.parquet")
    L = []
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    yrs = (days[-1] - days[0]).days / 365.25

    # ---- per symbol x combo table
    rows = []
    for s in res:
        for c in COMBOS:
            n, gr = stats(net[s][c]), stats(gross[s][c])
            rows.append(dict(symbol=s, combo=c, net_ann=n["ann_ret"], net_sharpe=n["sharpe"], net_t=n["t"],
                             net_mdd=n["mdd"], gross_ann=gr["ann_ret"], gross_sharpe=gr["sharpe"],
                             fees_ann=fees[s][c].mean() * 365, funding_ann=fund[s][c].mean() * 365,
                             fills_per_day=res[s]["data"][(c, "n_fills")] / len(days),
                             stops_per_year=res[s]["data"][(c, "n_stops")] / yrs))
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "symbol_combo.csv", index=False)
    L.append("Per symbol x combo (capital 1, max 1x gross notional; ann = mean daily P&L x 365; mdd in capital units)\n"
             + tab.round(3).to_string(index=False))

    # ---- baskets
    def basket(d, syms):
        return sum(d[s] for s in syms) / len(syms)
    B = {"disc": (basket(net, DISC), basket(gross, DISC)), "hold": (basket(net, HOLD), basket(gross, HOLD)),
         "all6": (basket(net, DISC + HOLD), basket(gross, DISC + HOLD))}
    rows = []
    for b, (bn, bg) in B.items():
        for c in COMBOS:
            n, gr = stats(bn[c]), stats(bg[c])
            syms = DISC if b == "disc" else HOLD if b == "hold" else DISC + HOLD
            avg_sym_sharpe = np.mean([sharpe(net[s][c].to_numpy()) for s in syms])
            rows.append(dict(basket=b, combo=c, net_ann=n["ann_ret"], net_sharpe=n["sharpe"], net_t=n["t"],
                             net_mdd=n["mdd"], gross_ann=gr["ann_ret"], gross_sharpe=gr["sharpe"], gross_t=gr["t"],
                             avg_symbol_net_sharpe=avg_sym_sharpe))
    bt = pd.DataFrame(rows)
    bt.to_csv(OUT / "baskets.csv", index=False)
    L.append("\nEqual-weight baskets\n" + bt.round(3).to_string(index=False))
    sel = bt[bt.basket == "disc"].sort_values("net_sharpe", ascending=False).iloc[0]["combo"]
    L.append(f"\nSelected on discovery (max net Sharpe): {sel}; pre-registered primary: {PRIMARY}")
    show = list(dict.fromkeys([PRIMARY, sel]))

    # ---- yearly
    for c in show:
        for b, (bn, bg) in B.items():
            yn = bn[c].groupby(bn.index.year)
            yg = bg[c].groupby(bg.index.year)
            t = pd.DataFrame({"net_ret": yn.sum(), "net_sharpe": yn.apply(lambda x: sharpe(x.to_numpy())),
                              "net_t": yn.apply(lambda x: tstat(x.to_numpy())), "gross_ret": yg.sum(),
                              "gross_sharpe": yg.apply(lambda x: sharpe(x.to_numpy()))})
            L.append(f"\nYearly {c} basket={b}\n" + t.round(3).to_string())

    # ---- regimes (ex post): pooled symbol-days, terciles per symbol
    for c in show:
        for grp, syms in (("disc", DISC), ("hold", HOLD)):
            frames = []
            for s in syms:
                r = res[s]
                f = pd.DataFrame({"net": net[s][c].to_numpy(), "gross": gross[s][c].to_numpy(),
                                  "rv": r["rv"], "er": r["er"], "absret": np.abs(r["ret"]), "ret": r["ret"]})
                f = f.dropna(subset=["er"])
                f["rv_t"] = pd.qcut(f["rv"], 3, labels=["lowVol", "midVol", "highVol"])
                f["er_t"] = pd.qcut(f["er"], 3, labels=["range(lowER)", "midER", "trend(highER)"])
                frames.append(f)
            f = pd.concat(frames, ignore_index=True).dropna(subset=["er", "rv"])
            for key in ("rv_t", "er_t"):
                g = f.groupby(key, observed=True)
                t = pd.DataFrame({"n": g.size(), "net_bp": g["net"].mean() * 1e4,
                                  "net_t": g["net"].apply(lambda x: tstat(x.to_numpy())),
                                  "gross_bp": g["gross"].mean() * 1e4,
                                  "gross_t": g["gross"].apply(lambda x: tstat(x.to_numpy()))})
                L.append(f"\nRegime {key} {c} {grp} (bp of capital per symbol-day)\n" + t.round(2).to_string())
            # 3x3 ER x RV gross
            t = f.pivot_table(index="er_t", columns="rv_t", values="gross", aggfunc="mean", observed=True) * 1e4
            L.append(f"gross bp by ER (rows) x RV (cols) {c} {grp}\n" + t.round(1).to_string())
            b, tt = nw_ols(f["gross"].to_numpy(), np.column_stack([f["er"] - f["er"].mean(), f["rv"] - f["rv"].mean()]))
            L.append(f"OLS gross ~ ER + RV (pooled, NW t): const {b[0]*1e4:.2f}bp (t {tt[0]:.2f}), "
                     f"ER {b[1]*1e4:.1f}bp/unit (t {tt[1]:.2f}), RV {b[2]*1e4:.1f}bp/unit (t {tt[2]:.2f})")

    # ---- CPCV PBO
    for b in ("disc", "hold"):
        cp = run_cpcv(B[b][0][COMBOS], n_groups=10, k_test=2, embargo=5)
        oos = cp.paths.mean(axis=1)
        L.append(f"\nCPCV basket={b} net: PBO={cp.pbo:.3f}; OOS path-mean Sharpe={sharpe(oos.to_numpy()):.2f}; "
                 f"chosen combos: {cp.chosen['combo'].value_counts().to_dict()}")

    # ---- momentum complementarity
    mom = pd.read_parquet(MOM)["final config"]
    mom.index = pd.DatetimeIndex(mom.index)
    for c in show:
        g6 = B["all6"][0][c]
        gd = B["disc"][0][c]
        for nm, g in (("all6", g6), ("disc", gd)):
            common = mom.index.intersection(g.index)
            corr = np.corrcoef(mom.loc[common], g.loc[common])[0, 1]
            cal = g.loc["2022-01-01":"2026-11-17"]
            m_cal = mom.reindex(cal.index).fillna(0.0)
            # vol-match the grid to momentum (full-sample scale, descriptive) for 50/50
            scale = m_cal.std() / cal.std()
            c50 = 0.5 * m_cal + 0.5 * cal * scale
            # trailing inverse-vol weights (60d, lagged one day)
            vm = m_cal.rolling(60, min_periods=20).std().shift(1)
            vg = cal.rolling(60, min_periods=20).std().shift(1)
            wm = (1 / vm) / (1 / vm + 1 / vg)
            civ = (wm * m_cal + (1 - wm) * cal * scale).dropna()
            L.append(f"\nMomentum combo {c} grid={nm}: corr(session days, n={len(common)})={corr:.3f}; "
                     f"momentum Sharpe(cal)={sharpe(m_cal.to_numpy()):.2f} MDD={mdd_additive(m_cal.to_numpy()):.3f}; "
                     f"grid Sharpe={sharpe(cal.to_numpy()):.2f} MDD={mdd_additive(cal.to_numpy()):.3f}; "
                     f"50/50 vol-matched Sharpe={sharpe(c50.to_numpy()):.2f} MDD={mdd_additive(c50.to_numpy()):.3f}; "
                     f"inv-vol Sharpe={sharpe(civ.to_numpy()):.2f} MDD={mdd_additive(civ.to_numpy()):.3f}")
    txt = "\n".join(L)
    (OUT / "summary.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
