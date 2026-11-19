"""Runner: backtests ideas A–E (pre-registered grid x execution modes) on the
discovery (BTC/ETH/SOL) and hold-out (BNB/XRP/DOGE) sets and writes the tables.

    python3 -m crypto_range.run            # full run (re-uses results/trades.parquet if present)
    python3 -m crypto_range.run --fresh    # recompute all trades
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_intraday_momentum.cpcv import run_cpcv
from crypto_intraday_momentum.data import load_funding, load_klines
from crypto_intraday_momentum.sessions import build_sessions
from crypto_intraday_momentum.sizing import combine, metrics

from .engine import Exec, simulate
from .strategies import GRID, IDEAS, PRIMARY, SPECS, label, rolling_band

OUT = Path(__file__).resolve().parent / "results"
DISC = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
HOLD = ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]
MODES = ["taker", "maker"]
MOM = Path(__file__).resolve().parents[1] / "crypto_intraday_momentum/results/walkforward/oos_curves.parquet"


def ppy(idea: str) -> float:
    return 365.0 if SPECS[idea].calendar == "all" else 252.0


# ----------------------------------------------------------------------------- backtests

def run_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (trades, session returns). Session returns: rows = (symbol, idea, date),
    columns = '<variant>|<mode>'."""
    all_tr, all_sr = [], []
    for sym in DISC + HOLD:
        df = load_klines(sym, "2021-01", "2026-11")
        fund = load_funding(sym, "2021-01", "2026-10")
        band = rolling_band(df, 120)
        mats = {}
        for idea in "ABCDEF":
            spec = SPECS[idea]
            if spec.name not in mats:
                mats[spec.name] = build_sessions(df, spec)
            m = mats[spec.name]
            cols = {}
            for p in GRID[idea]:
                o = IDEAS[idea](m, df=df, band=band, **p)
                for mode in MODES:
                    t = simulate(m, o, Exec(mode=mode), fund, sym)
                    t["idea"], t["variant"], t["mode"] = idea, label(p), mode
                    all_tr.append(t)
                    r = pd.Series(0.0, index=m.dates)
                    if len(t):
                        g = t.groupby("date")["net"].sum()
                        r.loc[g.index] = g.to_numpy()
                    cols[f"{label(p)}|{mode}"] = r
            sr = pd.DataFrame(cols)
            sr.index.name = "date"
            sr = sr.reset_index()
            sr["symbol"], sr["idea"] = sym, idea
            all_sr.append(sr)
        print(f"{sym} done", file=sys.stderr, flush=True)
    return pd.concat(all_tr, ignore_index=True), pd.concat(all_sr, ignore_index=True)


def basket(sr: pd.DataFrame, idea: str, syms: list[str], col: str, warmup: int = 25) -> pd.Series:
    """Equal-weight basket (each symbol 1/len(syms) notional), first `warmup` sessions dropped."""
    d = sr[(sr["idea"] == idea) & sr["symbol"].isin(syms)]
    w = d.pivot_table(index="date", columns="symbol", values=col).sort_index()
    w = w.iloc[warmup:]
    return w.fillna(0.0).sum(axis=1) / len(syms)


# ----------------------------------------------------------------------------- tables

def trade_stats(t: pd.DataFrame) -> dict:
    n = len(t)
    if n < 2:
        return dict(n=n, gross_mid_bp=np.nan, gross_bp=np.nan, net_bp=np.nan, t=np.nan, win=np.nan)
    x = t["net"]
    return dict(n=n, gross_mid_bp=t["gross_mid"].mean() * 1e4, gross_bp=t["gross"].mean() * 1e4,
                net_bp=x.mean() * 1e4, t=x.mean() / x.std(ddof=1) * np.sqrt(n),
                win=(x > 0).mean(), maker_entry=t["entry_maker"].mean(),
                maker_exit=t["exit_maker"].mean())


def sess_stats(r: pd.Series, p: float) -> dict:
    mt = metrics(r, p)
    return dict(sharpe=mt["sharpe"], ann_ret=r.mean() * p, mdd=mt["mdd"], sess_t=mt["t"])


def fmt(df: pd.DataFrame, floatfmt="{:.2f}") -> str:
    return df.to_string(float_format=lambda v: floatfmt.format(v))


def us_abs_move(sym: str = "BTCUSDT") -> pd.Series:
    from crypto_intraday_momentum.sessions import US
    m = build_sessions(load_klines(sym, "2021-01", "2026-11"), US)
    return pd.Series(np.abs(m.C[:, -1] / m.O[:, 0] - 1.0), index=m.dates)


def detail_report(say, tr, sr, idea, mom):
    v = label(PRIMARY[idea])
    p = ppy(idea)
    say(f"---- detail: idea {idea} primary {v}")
    # per symbol
    rows = []
    for mode in MODES:
        for sym in DISC + HOLD:
            t = tr[(tr["idea"] == idea) & (tr["variant"] == v) & (tr["mode"] == mode) & (tr["symbol"] == sym)]
            r = basket(sr, idea, [sym], f"{v}|{mode}")
            rows.append(dict(mode=mode, symbol=sym, **trade_stats(t), **sess_stats(r, p)))
    say(fmt(pd.DataFrame(rows).set_index(["mode", "symbol"])))
    say("")
    # time split
    rows = []
    for mode in MODES:
        for set_name, syms in (("disc", DISC), ("hold", HOLD)):
            t = tr[(tr["idea"] == idea) & (tr["variant"] == v) & (tr["mode"] == mode) & tr["symbol"].isin(syms)]
            r = basket(sr, idea, syms, f"{v}|{mode}")
            for per, lo, hi in (("2021-23", 2021, 2023), ("2024-26", 2024, 2026)):
                tt = t[(t["date"].dt.year >= lo) & (t["date"].dt.year <= hi)]
                rr = r[(r.index.year >= lo) & (r.index.year <= hi)]
                rows.append(dict(mode=mode, set=set_name, period=per, **trade_stats(tt), **sess_stats(rr, p)))
    say("time split:")
    say(fmt(pd.DataFrame(rows).set_index(["mode", "set", "period"])))
    say("")
    # combination with momentum
    for mode in MODES:
        r = basket(sr, idea, DISC, f"{v}|{mode}")
        if SPECS[idea].calendar == "all":
            if SPECS[idea].name == "off":
                r.index = r.index + pd.Timedelta(days=1)
            idx = pd.date_range("2022-01-01", mom.index[-1], freq="D")
            pp = 365.0
        else:
            idx = mom.index
            pp = 252.0
        M = mom.reindex(idx).fillna(0.0)
        Rr = r.reindex(idx).fillna(0.0)
        scale = M.std() / Rr.std()
        combos = {
            "momentum": M,
            "range (unit)": Rr,
            "range (vol-matched)": Rr * scale,
            "50/50 vol-matched": 0.5 * M + 0.5 * Rr * scale,
            "inverse-vol (trailing 60)": combine({"mom": M, "rng": Rr}, "inv_vol", 60),
        }
        rows = {k: metrics(x, pp) for k, x in combos.items()}
        say(f"combination, mode {mode}: corr = {np.corrcoef(M, Rr)[0, 1]:.3f}, "
            f"vol-match scale = {scale:.2f}x (ex-post)")
        say(fmt(pd.DataFrame(rows).T[["sharpe", "cagr", "vol", "mdd", "calmar", "t"]], "{:.3f}"))
        yr = pd.DataFrame({k: x.groupby(x.index.year).apply(lambda z: z.mean() / z.std() * np.sqrt(pp))
                           for k, x in combos.items() if k != "range (vol-matched)"})
        yr["corr"] = pd.concat([M, Rr], axis=1).groupby(M.index.year).apply(
            lambda d: np.corrcoef(d.iloc[:, 0], d.iloc[:, 1])[0, 1])
        say("yearly Sharpe:")
        say(fmt(yr))
        # conditional on regime (descriptive, contemporaneous)
        if SPECS[idea].calendar == "xnys":
            mv = us_abs_move().reindex(idx)
            q = pd.qcut(mv, 3, labels=["quiet", "normal", "trend"])
            g = pd.DataFrame({"momentum_bp": M * 1e4, "range_vm_bp": Rr * scale * 1e4}).groupby(q, observed=True)
            say("mean bp/session by BTC US-session |move| tercile (contemporaneous, descriptive):")
            say(fmt(g.mean()))
            lose = M < 0
            say(f"range (vol-matched) mean on momentum-losing days {Rr[lose].mean()*scale*1e4:.2f} bp, "
                f"on momentum-winning days {Rr[M > 0].mean()*scale*1e4:.2f} bp, "
                f"flat days {Rr[M == 0].mean()*scale*1e4:.2f} bp")
        say("")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    tp, sp = OUT / "trades.parquet", OUT / "session_returns.parquet"
    if a.fresh or not (tp.exists() and sp.exists()):
        tr, sr = run_all()
        tr.to_parquet(tp)
        sr.to_parquet(sp)
    tr, sr = pd.read_parquet(tp), pd.read_parquet(sp)

    rep = io.StringIO()

    def say(*x):
        print(*x, file=rep)
        print(*x)

    say("crypto_range — mean-reversion ideas, unit notional per trade, equal-weight baskets")
    say("discovery = BTC/ETH/SOL, hold-out = BNB/XRP/DOGE; net = after fees, slippage, funding")
    say("")

    # ---- 1. primaries
    rows = []
    for idea in "ABCDEF":
        v = label(PRIMARY[idea])
        for mode in MODES:
            for set_name, syms in (("disc", DISC), ("hold", HOLD)):
                t = tr[(tr["idea"] == idea) & (tr["variant"] == v) & (tr["mode"] == mode)
                       & tr["symbol"].isin(syms)]
                r = basket(sr, idea, syms, f"{v}|{mode}")
                rows.append(dict(idea=idea, variant=v, mode=mode, set=set_name,
                                 **trade_stats(t), **sess_stats(r, ppy(idea))))
    prim = pd.DataFrame(rows).set_index(["idea", "mode", "set"])
    say("== 1. Pre-registered primaries (per-trade bp; session Sharpe of the basket) ==")
    say(fmt(prim.drop(columns=["variant"])))
    say("")

    # ---- 2. grid (sensitivity) + PBO
    say("== 2. Sensitivity grid: net bp/trade (t) and basket session Sharpe ==")
    grid_rows, pbo_rows = [], []
    for idea in "ABCDEF":
        Rd = {}
        for p in GRID[idea]:
            v = label(p)
            for mode in MODES:
                col = f"{v}|{mode}"
                row = dict(idea=idea, variant=v, mode=mode)
                for set_name, syms in (("disc", DISC), ("hold", HOLD)):
                    t = tr[(tr["idea"] == idea) & (tr["variant"] == v) & (tr["mode"] == mode)
                           & tr["symbol"].isin(syms)]
                    st = trade_stats(t)
                    r = basket(sr, idea, syms, col)
                    row.update({f"{set_name}_n": st["n"], f"{set_name}_net_bp": st["net_bp"],
                                f"{set_name}_t": st["t"],
                                f"{set_name}_sharpe": sess_stats(r, ppy(idea))["sharpe"]})
                    if set_name == "disc":
                        Rd[col] = r
                grid_rows.append(row)
        R = pd.DataFrame(Rd).dropna()
        cp = run_cpcv(R, n_groups=10, k_test=2, embargo=20)
        best_is = cp.chosen["combo"].value_counts()
        pbo_rows.append(dict(idea=idea, n_configs=R.shape[1], pbo=cp.pbo,
                             oos_path_sharpe_med=float(np.median(
                                 cp.paths.mean() / cp.paths.std() * np.sqrt(ppy(idea)))),
                             most_chosen=best_is.index[0], chosen_share=best_is.iloc[0] / best_is.sum()))
    grid = pd.DataFrame(grid_rows).set_index(["idea", "variant", "mode"])
    say(fmt(grid))
    say("")
    say("== 3. CPCV over each idea's grid x modes (discovery basket, N=10, k=2, embargo 20) ==")
    pbo = pd.DataFrame(pbo_rows).set_index("idea")
    say(fmt(pbo))
    say("")

    # ---- 4. yearly table of primaries, maker
    say("== 4. Yearly (pre-registered primaries): basket mean bp per session / Sharpe ==")
    for mode in MODES:
        yr = {}
        for idea in "ABCDEF":
            v = label(PRIMARY[idea])
            for set_name, syms in (("disc", DISC), ("hold", HOLD)):
                r = basket(sr, idea, syms, f"{v}|{mode}")
                g = r.groupby(r.index.year)
                yr[(idea, set_name, "bp")] = g.mean() * 1e4
                yr[(idea, set_name, "SR")] = g.mean() / g.std() * np.sqrt(ppy(idea))
        say(f"-- mode {mode}")
        say(fmt(pd.DataFrame(yr).T))
        say("")

    # ---- 5. per-trade yearly for best grid row per idea (by discovery maker Sharpe) - descriptive
    say("== 5. Per-trade net bp by year, discovery, primaries ==")
    yt = {}
    for idea in "ABCDEF":
        v = label(PRIMARY[idea])
        for mode in MODES:
            t = tr[(tr["idea"] == idea) & (tr["variant"] == v) & (tr["mode"] == mode)
                   & tr["symbol"].isin(DISC)]
            g = t.groupby(t["date"].dt.year)["net"]
            yt[(idea, mode, "bp")] = g.mean() * 1e4
            yt[(idea, mode, "t")] = g.mean() / g.std() * np.sqrt(g.size())
    say(fmt(pd.DataFrame(yt).T))
    say("")

    # ---- 6. complementarity with momentum
    say("== 6. Complementarity with momentum 'final config' (2022-01..2026-11, calendar days) ==")
    mom = pd.read_parquet(MOM)["final config"]
    mom.index = pd.DatetimeIndex(mom.index)
    cal = pd.date_range("2022-01-01", mom.index[-1], freq="D")
    momc = mom.reindex(cal).fillna(0.0)
    comp_rows, corr_rows = [], []
    for idea in "ABCDEF":
        v = label(PRIMARY[idea])
        for mode in MODES:
            r = basket(sr, idea, DISC, f"{v}|{mode}")
            if SPECS[idea].name == "off":
                r.index = r.index + pd.Timedelta(days=1)     # 20:00 D -> 08:00 D+1: label by end date
            rc = r.reindex(cal).fillna(0.0)
            on = mom.index.intersection(r.index)
            c_all = np.corrcoef(momc, rc)[0, 1]
            c_on = np.corrcoef(mom.loc[on], r.loc[on])[0, 1]
            corr_rows.append(dict(idea=idea, mode=mode, corr_calendar=c_all, corr_common_days=c_on))
    say(fmt(pd.DataFrame(corr_rows).set_index(["idea", "mode"]), "{:.3f}"))
    say("")

    # ---- 7. chosen idea (pre-registered rule) and the post-hoc F
    cand = prim.xs(("maker", "disc"), level=("mode", "set"))
    chosen = cand.loc[list("ABCDE"), "sharpe"].idxmax()
    say(f"== 7. Pre-registered pick among A-E (best discovery maker Sharpe): {chosen} "
        f"(Sharpe {cand.loc[chosen, 'sharpe']:.2f}) ==")
    say("")
    for idea in dict.fromkeys([chosen, "F"]):
        detail_report(say, tr, sr, idea, mom)
    (OUT / "report.txt").write_text(rep.getvalue())
    return tr, sr, prim, grid, pbo


if __name__ == "__main__":
    main()
