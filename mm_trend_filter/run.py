"""Stage-1 screen (DESIGN.md).

    python -m mm_trend_filter.run                                   # discovery BTC/ETH/SOL
    python -m mm_trend_filter.run --symbols BNBUSDT XRPUSDT DOGEUSDT --tag holdout
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_intraday_momentum.data import load_klines
from crypto_intraday_momentum.sessions import US, build_sessions
from crypto_intraday_momentum.signals import compute_signals

from .policies import POLICIES, path_length_state, permissions, window_state
from .sim import ANCHOR, MID, simulate

CACHE = Path(r"C:\Users\smile-user\strategy-hypothesis-lab\crypto_intraday_momentum\data_cache")
OUT = Path(__file__).resolve().parent / "reports"
START, END = "2021-01-01", "2026-11-18"
CAP, TAKER = 5, 0.0005
DELTAS = [0.0005, 0.0010, 0.0020]
MODES = {"anchor": ANCHOR, "mid": MID}
PRIMARY = ("anchor", 0.0010)
N_RANDOM, BLOCK, N_BOOT = 200, 20, 2000


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_symbol(sym):
    df = load_klines(sym, START, END, cache=CACHE)
    m = build_sessions(df, US)
    sig = compute_signals(m)
    ok = m.tradable & np.isfinite(sig.sigma).all(axis=1) & np.isfinite(sig.prev_close)
    o0 = m.O[ok, 0][:, None]
    P = {k: getattr(m, k)[ok] / o0 for k in "OHLC"}
    state = window_state(sig)[ok]
    vol = path_length_state(P["C"], P["O"][:, 0], sig.dec_min)
    return {"dates": m.dates[ok], "P": P, "state": state, "vol": vol, "dm": sig.dec_min}


def run_one(d, mode, delta, name, rng=None, p=None):
    n_k = d["P"]["C"].shape[1]
    ab, aa, fl = permissions(name, d["state"], d["dm"], n_k, d["vol"], rng, p)
    P = d["P"]
    eq, nf = simulate(P["O"], P["H"], P["L"], P["C"], ab, aa, fl, delta, MODES[mode], CAP, TAKER)
    return eq, nf, ab | aa


def window_pnl(eq, dm):
    """(n_sess, 1 + n_dec): PnL of the pre window [0, dm0) and of each decision window."""
    ends = np.append(dm, eq.shape[1]) - 1
    e = np.concatenate([np.zeros((eq.shape[0], 1)), eq[:, ends]], axis=1)
    return np.diff(e, axis=1)


def block_boot(x: np.ndarray, stat=np.mean, seed=0):
    rng = np.random.default_rng(seed)
    n = len(x)
    nb = int(np.ceil(n / BLOCK))
    out = np.empty(N_BOOT)
    for b in range(N_BOOT):
        st = rng.integers(0, n - BLOCK + 1, nb)
        idx = (st[:, None] + np.arange(BLOCK)[None, :]).ravel()[:n]
        out[b] = stat(x[idx])
    return np.percentile(out, [2.5, 97.5])


def tstat(x):
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))


def pooled(series: dict) -> pd.Series:
    """Sum over symbols per session date (inner join: dates every symbol has)."""
    return pd.concat(series, axis=1, join="inner").sum(axis=1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--tag", default="discovery")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    data = {}
    for s in a.symbols:
        log(f"loading {s}")
        data[s] = load_symbol(s)
        log(f"{s}: {len(data[s]['dates'])} sessions, broken-window share "
            f"{(data[s]['state'] != 0).mean():.3f}, vol_off share {data[s]['vol'].mean():.3f}")

    rows, yearly_rows, c1_rows, rand_rows = [], [], [], []
    for mode in MODES:
        for delta in DELTAS:
            sess = {pol: {} for pol in POLICIES}
            extra = {pol: {"fills": [], "quoting": []} for pol in POLICIES}
            win = {}
            for s, d in data.items():
                for pol in POLICIES:
                    eq, nf, quoting = run_one(d, mode, delta, pol)
                    sess[pol][s] = pd.Series(eq[:, -1] * 1e4, index=d["dates"])
                    extra[pol]["fills"].append(nf.sum(axis=1).mean())
                    extra[pol]["quoting"].append(quoting.mean())
                    if pol == "none":
                        win[s] = window_pnl(eq, d["dm"]) * 1e4
            pool = {pol: pooled(sess[pol]) for pol in POLICIES}
            base = pool["none"]
            for pol in POLICIES:
                dlt = (pool[pol] - base).to_numpy()
                yr = (pool[pol] - base).groupby(pool[pol].index.year).mean()
                lo, hi = block_boot(dlt)
                rows.append({"mode": mode, "delta_bp": delta * 1e4, "policy": pol,
                             "pnl_bp_per_session": pool[pol].mean(), "improvement_bp": dlt.mean(),
                             "improvement_mean_of_years": yr.mean(), "ci_lo": lo, "ci_hi": hi,
                             "t": tstat(dlt) if pol != "none" else np.nan,
                             "years_positive": int((yr > 0).sum()) if pol != "none" else np.nan,
                             "n_years": len(yr), "n_sessions": len(dlt),
                             "quoting_share": np.mean(extra[pol]["quoting"]),
                             "fills_per_session": np.sum(extra[pol]["fills"])})
                for y, v in yr.items():
                    yearly_rows.append({"mode": mode, "delta_bp": delta * 1e4, "policy": pol, "year": y,
                                        "improvement_bp": v, "pnl_bp": pool[pol][pool[pol].index.year == y].mean()})

            # C1: broken vs inside windows under `none`, per date sums so the bootstrap resamples sessions
            per = []
            for s, d in data.items():
                st = np.concatenate([np.zeros((d["state"].shape[0], 1), int), d["state"]], axis=1) != 0
                w = win[s]
                per.append(pd.DataFrame({"b_sum": np.where(st, w, 0).sum(1), "b_n": st.sum(1),
                                         "i_sum": np.where(~st, w, 0).sum(1), "i_n": (~st).sum(1)},
                                        index=d["dates"]))
            common = per[0].index
            for x in per[1:]:
                common = common.intersection(x.index)
            g = pd.concat([x.loc[common] for x in per]).groupby(level=0).sum()
            arr = g[["b_sum", "b_n", "i_sum", "i_n"]].to_numpy()

            def diff(x):
                return x[:, 0].sum() / x[:, 1].sum() - x[:, 2].sum() / x[:, 3].sum()

            lo, hi = block_boot(arr, stat=diff)
            yd = g.groupby(g.index.year).apply(lambda x: diff(x[["b_sum", "b_n", "i_sum", "i_n"]].to_numpy()))
            c1_rows.append({"mode": mode, "delta_bp": delta * 1e4, "broken_mean_bp": arr[:, 0].sum() / arr[:, 1].sum(),
                            "inside_mean_bp": arr[:, 2].sum() / arr[:, 3].sum(), "diff_bp": diff(arr),
                            "diff_mean_of_years": yd.mean(), "ci_lo": lo, "ci_hi": hi,
                            "n_broken": int(arr[:, 1].sum()), "n_inside": int(arr[:, 3].sum())})

            # random-off control with band_off's off share per symbol
            imps = []
            for seed in range(N_RANDOM):
                rng = np.random.default_rng(1000 + seed)
                ser = {}
                for s, d in data.items():
                    p = (d["state"] != 0).mean()
                    eq, _, _ = run_one(d, mode, delta, "random_off", rng=rng, p=p)
                    ser[s] = pd.Series(eq[:, -1] * 1e4, index=d["dates"])
                imps.append((pooled(ser) - base).mean())
            imps = np.array(imps)
            rand_rows.append({"mode": mode, "delta_bp": delta * 1e4, "random_mean": imps.mean(),
                              "random_p05": np.percentile(imps, 5), "random_p95": np.percentile(imps, 95)})
            log(f"{mode} δ={delta * 1e4:.0f}bp done")

    res, yrs, c1, rnd = map(pd.DataFrame, (rows, yearly_rows, c1_rows, rand_rows))
    tag = a.tag
    res.to_csv(OUT / f"stage1_{tag}.csv", index=False)
    yrs.to_csv(OUT / f"stage1_{tag}_yearly.csv", index=False)
    c1.to_csv(OUT / f"stage1_{tag}_c1.csv", index=False)
    rnd.to_csv(OUT / f"stage1_{tag}_random.csv", index=False)

    pm, pdlt = PRIMARY[0], PRIMARY[1] * 1e4
    r = res[(res["mode"] == pm) & (res["delta_bp"] == pdlt)].set_index("policy")
    c = c1[(c1["mode"] == pm) & (c1["delta_bp"] == pdlt)].iloc[0]
    q = rnd[(rnd["mode"] == pm) & (rnd["delta_bp"] == pdlt)].iloc[0]
    band = ["band_off", "band_flat", "band_skew", "sticky_off"]
    best = r.loc[band, "improvement_bp"].idxmax()
    crit = {
        "C1 broken windows worse (CI < 0)": bool(c["ci_hi"] < 0),
        "C2 band_off > random p95": bool(r.loc["band_off", "improvement_bp"] > q["random_p95"]),
        f"C3 best band ({best}) > vol_off": bool(r.loc[best, "improvement_bp"] > r.loc["vol_off", "improvement_bp"]),
        "C4 band_off positive in >= 4 of 6 years": bool(r.loc["band_off", "years_positive"] >= 4),
    }
    lines = [f"# MM trend filter, stage 1: {tag}", "",
             f"Symbols {', '.join(a.symbols)}; {START} .. {END}; NYSE sessions; cap {CAP} units; maker 0 bp, "
             f"taker {TAKER * 1e4:.0f} bp. PnL in bp of one unit notional per session, summed over symbols.", "",
             f"## Criteria (primary: {pm}, δ = {pdlt:.0f} bp)", ""]
    lines += [f"- {k}: **{'pass' if v else 'fail'}**" for k, v in crit.items()]
    lines += ["", "## Policies", "", res.to_markdown(index=False, floatfmt=".3f"), "",
              "## C1: window PnL under `none`", "", c1.to_markdown(index=False, floatfmt=".3f"), "",
              "## Random-off control (improvement over none)", "", rnd.to_markdown(index=False, floatfmt=".3f"), "",
              f"## Yearly improvement ({pm}, δ = {pdlt:.0f} bp)", "",
              yrs[(yrs["mode"] == pm) & (yrs["delta_bp"] == pdlt)]
              .pivot(index="year", columns="policy", values="improvement_bp").to_markdown(floatfmt=".3f"), ""]
    (OUT / f"stage1_{tag}.md").write_text("\n".join(lines), encoding="utf-8")
    pd.set_option("display.width", 250)
    print(res.round(3).to_string(index=False))
    print(c1.round(3).to_string(index=False))
    print(rnd.round(3).to_string(index=False))
    for k, v in crit.items():
        print(k, "PASS" if v else "FAIL")


if __name__ == "__main__":
    main()
