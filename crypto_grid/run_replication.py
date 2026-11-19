"""Step 1-3: faithful replication of the DGT paper, fill-realism variants, and the
beta vs grid-profit decomposition.

    python3 -m crypto_grid.run_replication

Writes crypto_grid/results/replication/{grid.csv, summary.txt}.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .data import load_klines_local, ohlc_arrays
from .engine import dgt_code_replica, mark_to_market, run_dgt
from .metrics import cagr, day_end_bars, max_drawdown, nw_ols, xirr

OUT = Path(__file__).parent / "results" / "replication"
START, END = "2021-01-01", "2024-07-31 23:59"
MONTHS = 43
GRID_SIZES = [0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.07, 0.1]   # paper Fig. 4/6, code config
HALVES = [2, 3, 5, 7, 10]                                         # authors' code config
FEE = 0.0008
M = 100.0

# variant name -> run_dgt kwargs (None = closed-form code replica)
VARIANTS = {
    "R0_code": None,
    "R0x_code_explicit": dict(levels="arith", fill="touch", reset="close", both_rule="code_path"),
    "R1_paper_text": dict(levels="geo", fill="touch", reset="close", both_rule="low_first", max_fills=1),
    "R2_realistic": dict(levels="geo", fill="through", reset="next_open", both_rule="ohlc", max_fills=1),
}


def evaluate(log, o, cl, idx, last, days, years, r_asset) -> dict:
    mk = mark_to_market(log, cl, last)
    E, money = mk["equity"], mk["money_in"]
    inj = np.zeros(len(last))
    for bar, amt in log.injections:
        inj[np.searchsorted(last, bar)] += amt
    prev = np.r_[0.0, E[:-1]]
    r = E / (prev + inj) - 1
    nav = np.cumprod(1 + r)
    t_years = (idx[np.array([b for b, _ in log.injections])] - idx[0]).total_seconds().to_numpy() / (365.25 * 86400)
    flows = np.r_[-np.array([a for _, a in log.injections]), E[-1]]
    times = np.r_[t_years, years]
    expo = mk["coins"] * mk["px"] / E
    wbar = float(expo.mean())
    nav_cm = np.cumprod(1 + wbar * r_asset)
    b, t = nw_ols(r[1:], r_asset[1:])
    # DCA buy-and-hold with exactly the same external cash flows
    coins_dca = sum(a / o[bar] * (1 - FEE) for bar, a in log.injections)
    v_dca = coins_dca * cl[-1]
    return dict(
        V_end=E[-1], money_in=money[-1], ratio=E[-1] / money[-1],
        irr_code=(E[-1] / money[-1]) ** (12 / MONTHS) - 1,
        xirr=xirr(times, flows), twr_cagr=cagr(np.r_[1.0, nav], years), twr_mdd=max_drawdown(np.r_[1.0, nav]),
        ratio_mdd=max_drawdown(E / money),
        realized=mk["realized"][-1], fees=mk["fees"][-1], bag_value=mk["bag"][-1] * cl[-1],
        n_fills=log.n_fills, n_resets=len(log.resets),
        n_up=sum(1 for _, s in log.resets if s == "up"), n_down=sum(1 for _, s in log.resets if s == "down"),
        avg_expo=wbar, beta=b[1], alpha_ann=b[0] * 365, alpha_t=t[0],
        cm_cagr=cagr(np.r_[1.0, nav_cm], years), cm_mdd=max_drawdown(np.r_[1.0, nav_cm]),
        dca_ratio=v_dca / money[-1], dca_irr_code=(v_dca / money[-1]) ** (12 / MONTHS) - 1,
        dca_xirr=xirr(times, np.r_[flows[:-1], v_dca]),
    ), pd.Series(r, index=days)


def run_symbol(sym: str):
    df = load_klines_local(sym, START, END)
    o, hi, lo, cl = ohlc_arrays(df)
    idx = df.index
    last, days = day_end_bars(idx)
    years = (idx[-1] + pd.Timedelta(minutes=1) - idx[0]).total_seconds() / (365.25 * 86400)
    px_d = cl[last]
    r_asset = px_d / np.r_[o[0], px_d[:-1]] - 1
    bh = dict(symbol=sym, start_px=o[0], end_px=cl[-1],
              bh_irr_code=(cl[-1] * (1 - FEE) / o[0]) ** (12 / MONTHS) - 1,
              bh_cagr=(cl[-1] / o[0]) ** (1 / years) - 1,
              bh_mdd_1m=max_drawdown(cl), bh_mdd_daily=max_drawdown(px_d))
    rows, rets = [], {}
    for k in GRID_SIZES:
        for h in HALVES:
            for name, kw in VARIANTS.items():
                if kw is None:
                    r = dgt_code_replica(o, hi, lo, cl, k, h, FEE, M, MONTHS)
                    rows.append(dict(symbol=sym, variant=name, grid_size=k, half=h, V_end=r["total_value"],
                                     money_in=r["money_input"], ratio=r["ratio"], irr_code=r["irr_code"],
                                     n_up=r["n_up_resets"], n_down=r["n_down_resets"]))
                    continue
                log = run_dgt(o, hi, lo, cl, k, h, FEE, M, **kw)
                met, r = evaluate(log, o, cl, idx, last, days, years, r_asset)
                rows.append(dict(symbol=sym, variant=name, grid_size=k, half=h, **met))
                rets[(name, k, h)] = r
    return bh, pd.DataFrame(rows), rets, pd.Series(r_asset, index=days)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bhs, grids, lines = [], [], []
    for sym in ["BTCUSDT", "ETHUSDT"]:
        bh, g, rets, ra = run_symbol(sym)
        bhs.append(bh)
        grids.append(g)
        pd.DataFrame({f"{a}|{b}|{c}": v for (a, b, c), v in rets.items()}).assign(asset=ra).to_parquet(
            OUT / f"daily_twr_{sym}.parquet")
    bh = pd.DataFrame(bhs).set_index("symbol")
    g = pd.concat(grids, ignore_index=True)
    g.to_csv(OUT / "grid.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    lines.append("Buy and hold (perp 1m, 2021-01-01 open .. 2024-07-31 close)\n" + bh.round(4).to_string())
    paper = {  # read off Fig. 4 / Fig. 6 (avg over grid numbers half), percent
        "BTCUSDT": {"irr": [27.8, 29.0, 29.6, 30.7, 32.4, 33.8, 35.5, 35.8], "mdd": [49.6, 46.3, 44.8, 43.6, 44.2, 42.8, 40.5, 37.7],
                    "bh": (22.3, 77.0)},
        "ETHUSDT": {"irr": [26.2, 27.2, 28.1, 28.8, 30.6, 33.2, 37.7, 43.2], "mdd": [54.0, 53.0, 55.0, 56.0, 54.6, 55.0, 49.8, 37.0],
                    "bh": (42.2, 82.0)},
    }
    for sym in ["BTCUSDT", "ETHUSDT"]:
        for var in VARIANTS:
            s = g[(g.symbol == sym) & (g.variant == var)].groupby("grid_size").mean(numeric_only=True)
            cols = [c for c in ["irr_code", "xirr", "twr_cagr", "twr_mdd", "ratio_mdd", "money_in", "dca_irr_code",
                                "dca_xirr", "avg_expo", "beta", "alpha_ann", "alpha_t", "cm_cagr", "cm_mdd",
                                "n_fills", "n_up", "n_down"] if c in s]
            t = s[cols].copy()
            t.insert(0, "paper_irr", paper[sym]["irr"])
            t.insert(1, "paper_mdd", paper[sym]["mdd"])
            lines.append(f"\n{sym} {var}: averages over half in {HALVES} (fractions; paper columns in %)\n"
                         + t.round(3).to_string())
        lines.append(f"paper B&H {sym}: IRR {paper[sym]['bh'][0]}%, MDD {paper[sym]['bh'][1]}%")
    # decomposition (realistic variant, every combo): total P&L = realized grid profit + inventory P&L
    d = g[g.variant.isin(["R0x_code_explicit", "R2_realistic"])].copy()
    d["pnl"] = d["V_end"] - d["money_in"]
    d["inventory_pnl"] = d["pnl"] - d["realized"]
    d["realized_share"] = d["realized"] / d["pnl"]
    dec = d.groupby(["symbol", "variant", "grid_size"])[["pnl", "realized", "inventory_pnl", "realized_share",
                                                         "fees", "bag_value", "money_in"]].mean()
    lines.append("\nP&L decomposition (USDT per 100 USDT principal, avg over half): realized grid round-trip profit "
                 "(net of fees) vs inventory/beta P&L\n" + dec.round(2).to_string())
    txt = "\n".join(lines)
    (OUT / "summary.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
