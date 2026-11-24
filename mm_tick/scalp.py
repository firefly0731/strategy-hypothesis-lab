"""Stage S: one-tick scalper with a band switch, simulated on trades only (see DESIGN.md).

    python -m mm_tick.scalp build   --symbols ADAUSDT ...
    python -m mm_tick.scalp summary
"""
from __future__ import annotations

import argparse
import gc
import logging

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from numba import njit

from . import events as E
from .anchored import anchored_z
from .revert import CHUNKS, cdf_by_day
from .run import MONTHS, RES, block_ci, ticks

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
           "ADAUSDT", "NEARUSDT", "WLDUSDT", "TRUMPUSDT", "FETUSDT")
U_ON = (1.0, 0.95, 0.8)
EXIT_U = (2.0, 0.99, 0.95)          # 2.0 = never liquidate on a band exit
TP_BP = 20.0
RULES = {"touch": 0, "through": 1}
R_MIN = 15
DELAY_MS = 250
TIMEOUT_MS = 1_800_000
TAKER_BP = 4.0
DESIGN_END = "2026-06"            # design half: days before 2026-06-01
START = pd.Timestamp(MONTHS[0] + "-01", tz="UTC")
log = logging.getLogger("mm_tick.scalp")


def u_series(sym: str) -> np.ndarray:
    """u (position of |z| in its 14-day distribution) for every second of MONTHS; NaN if unknown.
    Built chunk by chunk with a warm-up month, like stage R."""
    n_total = int((pd.Timestamp(MONTHS[-1] + "-01", tz="UTC") + pd.offsets.MonthBegin(1) - START).total_seconds())
    out = np.full(n_total, np.nan, dtype=np.float32)
    for target in CHUNKS:
        warm = MONTHS[MONTHS.index(target[0]) - 1]
        months = [warm] + target
        g = E.second_grid(sym, months)
        px = g["px"]
        del g
        az = anchored_z(px, R_MIN)
        del px
        cdf = cdf_by_day(az["z"], az["n_days"])
        z = az["z"]
        n = len(z)
        b = np.clip(np.searchsorted(E.EDGES, np.abs(z), side="left") - 1, 0, len(E.EDGES) - 2)
        u = cdf[np.arange(n) // E.DAY_S, b].astype(np.float32)
        u[~np.isfinite(z)] = np.nan
        del az, z, b, cdf
        off = int((pd.Timestamp(months[0] + "-01", tz="UTC") - START).total_seconds())
        warm_s = int((pd.Timestamp(target[0] + "-01", tz="UTC") - pd.Timestamp(warm + "-01", tz="UTC")).total_seconds())
        out[off + warm_s: off + n] = u[warm_s:]
        del u
        gc.collect()
    return out


@njit(cache=True)
def simulate(t, px, side, u, start_ms, tick, rule, u_on, delay, timeout, taker_bp, tp_bp=0.0, exit_u=2.0):
    """Returns (entry_ms, pnl_bp, by_tp) per round trip. side: +1 taker buy, -1 taker sell.
    Prices are in whole ticks (tick = 1). The take-profit is tp_bp from the entry rounded to ticks
    (at least one tick; tp_bp = 0 means one tick). In a position, u >= exit_u liquidates at once."""
    n = len(t)
    ent_t = np.empty(n // 2 + 1, dtype=np.int64)
    pnl = np.empty(n // 2 + 1)
    by_tp = np.empty(n // 2 + 1, dtype=np.bool_)
    k = 0
    bid_m = np.nan
    ask_m = np.nan
    q_bid = np.nan            # active resting quotes
    q_ask = np.nan
    p_bid = np.nan            # pending (in flight) target quotes
    p_ask = np.nan
    p_time = -1               # activation time of the pending update, -1 = none
    pos = 0
    entry = 0.0
    entry_t = 0
    tp = np.nan
    tp_time = 0
    for i in range(n):
        ti = t[i]
        p = px[i]
        s = side[i]
        # 1) pending quote update lands
        if p_time >= 0 and ti >= p_time:
            q_bid = p_bid
            q_ask = p_ask
            p_time = -1
        # 2) does this trade fill a resting order?
        if pos == 0:
            if s < 0 and q_bid == q_bid and ((rule == 0 and p <= q_bid) or (rule == 1 and p < q_bid)):
                pos = 1
                entry = q_bid
                entry_t = ti
                tp = entry + max(tick, np.rint(entry * tp_bp * 1e-4))
                tp_time = ti + delay
                q_bid = np.nan
                q_ask = np.nan
                p_time = -1
            elif s > 0 and q_ask == q_ask and ((rule == 0 and p >= q_ask) or (rule == 1 and p > q_ask)):
                pos = -1
                entry = q_ask
                entry_t = ti
                tp = entry - max(tick, np.rint(entry * tp_bp * 1e-4))
                tp_time = ti + delay
                q_bid = np.nan
                q_ask = np.nan
                p_time = -1
        else:
            closed = False
            if ti >= tp_time:
                if pos > 0 and s > 0 and ((rule == 0 and p >= tp) or (rule == 1 and p > tp)):
                    pnl[k] = (tp - entry) / entry * 1e4
                    by_tp[k] = True
                    closed = True
                elif pos < 0 and s < 0 and ((rule == 0 and p <= tp) or (rule == 1 and p < tp)):
                    pnl[k] = (entry - tp) / entry * 1e4
                    by_tp[k] = True
                    closed = True
            band_out = False
            if not closed and exit_u < 1.5:
                sec_e = (ti - start_ms) // 1000 - 1
                ue = u[sec_e] if 0 <= sec_e < len(u) else np.nan
                band_out = ue == ue and ue >= exit_u
            if not closed and (band_out or ti - entry_t >= timeout):
                # taker exit at the touch: sell to the bid / buy from the ask
                if pos > 0:
                    xp = bid_m if bid_m == bid_m else p
                    pnl[k] = (xp - entry) / entry * 1e4 - taker_bp
                else:
                    xp = ask_m if ask_m == ask_m else p
                    pnl[k] = (entry - xp) / entry * 1e4 - taker_bp
                by_tp[k] = False
                closed = True
            if closed:
                ent_t[k] = entry_t
                k += 1
                pos = 0
        # 3) update the market from this trade
        if s < 0:
            bid_m = p
            if ask_m == ask_m and ask_m <= bid_m:
                ask_m = bid_m + tick
        else:
            ask_m = p
            if bid_m == bid_m and bid_m >= ask_m:
                bid_m = ask_m - tick
        # 4) desired quotes while flat; changes take `delay` to land
        if pos == 0:
            sec = (ti - start_ms) // 1000 - 1
            ui = u[sec] if 0 <= sec < len(u) else np.nan
            allow = ui == ui and ui < u_on
            d_bid = bid_m if allow else np.nan
            d_ask = ask_m if allow else np.nan
            same = ((d_bid == q_bid) or (d_bid != d_bid and q_bid != q_bid)) and \
                   ((d_ask == q_ask) or (d_ask != d_ask and q_ask != q_ask))
            if not same:
                if p_time < 0:
                    p_time = ti + delay
                p_bid = d_bid
                p_ask = d_ask
    # close an open position at the end with a taker order
    if pos != 0:
        if pos > 0:
            pnl[k] = (bid_m - entry) / entry * 1e4 - taker_bp
        else:
            pnl[k] = (entry - ask_m) / entry * 1e4 - taker_bp
        by_tp[k] = False
        ent_t[k] = entry_t
        k += 1
    return ent_t[:k], pnl[:k], by_tp[:k]


def build(sym: str) -> None:
    p = RES / f"scalp_{sym}.parquet"
    if p.exists():
        return
    tick = ticks()[sym]
    u = u_series(sym)
    start_ms = int(START.timestamp() * 1000)
    rows = []
    for mo in MONTHS[1:]:                        # the first month is warm-up only
        tb = pq.read_table(E.trade_path(sym, mo), columns=["t", "px", "buyer_maker"])
        t = tb.column("t").to_numpy()
        px = np.rint(tb.column("px").to_numpy() / tick)      # whole ticks: exact comparisons
        side = np.where(tb.column("buyer_maker").to_numpy(), -1, 1).astype(np.int8)
        del tb
        for rname, r in RULES.items():
            for uo in U_ON:
                for xu in EXIT_U:
                    et, pl, tp = simulate(t, px, side, u, start_ms, 1.0, r, uo, DELAY_MS, TIMEOUT_MS,
                                          TAKER_BP, TP_BP, xu)
                    rows.append(pd.DataFrame({"rule": rname, "u_on": uo, "exit_u": xu, "t": et,
                                              "pnl_bp": pl.astype(np.float32), "by_tp": tp}))
        del t, px, side
        gc.collect()
        log.info("%s %s done", sym, mo)
    df = pd.concat(rows, ignore_index=True)
    df["day"] = (df["t"] - start_ms) // 86_400_000
    df["sym"] = sym
    df.to_parquet(p)


def summary() -> pd.DataFrame:
    df = pd.concat([pd.read_parquet(RES / f"scalp_{s}.parquet") for s in SYMBOLS if (RES / f"scalp_{s}.parquet").exists()],
                   ignore_index=True)
    cut = (pd.Timestamp(DESIGN_END + "-01", tz="UTC") - START).days
    df["half"] = np.where(df["day"] < cut, "design", "confirm")
    rows = []
    for (rule, uo, xu, half), x in df.groupby(["rule", "u_on", "exit_u", "half"]):
        dv = x.groupby("day")["pnl_bp"].agg(["sum", "count"]).rename(columns={"count": "n"})
        lo, hi = block_ci(dv)
        n_days = x["day"].nunique()
        rows.append({"rule": rule, "u_on": uo, "exit_u": xu, "half": half, "p01_bp": x["pnl_bp"].quantile(0.01), "trips": len(x), "trips_per_day": len(x) / n_days,
                     "tp_share": x["by_tp"].mean(), "pnl_bp": x["pnl_bp"].mean(), "ci_lo": lo, "ci_hi": hi,
                     "pnl_tp": x.loc[x.by_tp, "pnl_bp"].mean(), "pnl_timeout": x.loc[~x.by_tp, "pnl_bp"].mean()})
    out = pd.DataFrame(rows)
    per_sym = (df.groupby(["sym", "rule", "u_on", "exit_u"])["pnl_bp"].agg(["mean", "count"]).reset_index())
    out.to_csv(RES / "summary_scalp.csv", index=False)
    per_sym.to_csv(RES / "summary_scalp_by_symbol.csv", index=False)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "summary"])
    ap.add_argument("--symbols", nargs="*", default=list(SYMBOLS))
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    if a.cmd == "build":
        for s in a.symbols:
            build(s)
    else:
        pd.set_option("display.width", 250)
        print(summary().round(3).to_string(index=False))


if __name__ == "__main__":
    main()
