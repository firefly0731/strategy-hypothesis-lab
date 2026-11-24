"""Stage X: cross-sectional, monitored maker on Binance USDT-M (see DESIGN.md, Stage X).

    python -m mm_tick.xs build            # all symbols in universe_xs.csv
    python -m mm_tick.xs summary
"""
from __future__ import annotations

import argparse
import gc
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from numba import njit

from . import events as E
from .anchored import anchored_z
from .fetch_aggtrades import months_between
from .revert import cdf_by_day
from .run import RES, block_ci, ticks

# Each period: (first month = warm-up only, last month, split month between the two halves, labels).
# "main" is the pre-registered test; "early" is the extension that covers the 12 months before it.
PERIODS = {
    # v2 folders: runs with the effective (historical) tick; the first runs in xs/ and xs_early/
    # used today's tick and are kept only as the record of that bug
    "main": ("2026-04", "2026-10", "2026-08", ("design", "confirm"), "xs_v2"),
    "early": ("2025-04", "2025-11", "2025-08", ("early_a", "early_b"), "xs_early_v2"),   # cut for disk
}
PERIOD = "main"
MONTHS: list[str] = []
SIM_MONTHS: list[str] = []
START = None
DESIGN_END = ""
HALVES: tuple = ()
OUT = None


def set_period(name: str) -> None:
    global PERIOD, MONTHS, SIM_MONTHS, START, DESIGN_END, HALVES, OUT
    first, last, split, halves, sub = PERIODS[name]
    PERIOD = name
    MONTHS = months_between(first, last)
    SIM_MONTHS = MONTHS[1:]
    START = pd.Timestamp(MONTHS[0] + "-01", tz="UTC")
    DESIGN_END, HALVES, OUT = split, halves, RES / sub


UNIVERSE = Path(__file__).with_name("universe_xs.csv")
RS = (15, 5)
U_ON = (0.8, 1.0)
EXIT_U = 0.99
RULES = {"hybrid": 2, "touch": 0, "through": 1}
LIQUIDATE = {"hold": False, "liquidate": True}
MAKER_BP, TAKER_BP = 2.0, 5.0
DELAY_MS, TIMEOUT_MS = 250, 1_800_000
AS_LOOKBACK_D, SEL_LOOKBACK_D, SEL_MIN_TRIPS = 7, 7, 20
KEYS = ["R", "rule", "u_on", "exit"]      # variant columns (stage G uses its own)
NAME = "xs"
log = logging.getLogger("mm_tick.xs")
set_period("main")


def available(sym: str) -> list[str]:
    return [m for m in MONTHS if E.trade_path(sym, m).exists()]


def n_seconds() -> int:
    end = pd.Timestamp(MONTHS[-1] + "-01", tz="UTC") + pd.offsets.MonthBegin(1)
    return int((end - START).total_seconds())


def u_series(sym: str, R: int) -> np.ndarray:
    """u per second over MONTHS, built in chunks of up to 3 target months plus a warm-up month."""
    out = np.full(n_seconds(), np.nan, dtype=np.float32)
    targets = SIM_MONTHS
    for c in range(0, len(targets), 3):
        target = targets[c:c + 3]
        warm = MONTHS[MONTHS.index(target[0]) - 1]
        months = [warm] + target
        g = E.second_grid(sym, months, allow_missing=True)
        px = g["px"]
        del g
        az = anchored_z(px, R)
        del px
        cdf = cdf_by_day(az["z"], az["n_days"])
        z = az["z"]
        b = np.clip(np.searchsorted(E.EDGES, np.abs(z), side="left") - 1, 0, len(E.EDGES) - 2)
        u = cdf[np.arange(len(z)) // E.DAY_S, b].astype(np.float32)
        u[~np.isfinite(z)] = np.nan
        del az, z, b, cdf
        off = int((pd.Timestamp(months[0] + "-01", tz="UTC") - START).total_seconds())
        warm_s = int((pd.Timestamp(target[0] + "-01", tz="UTC") - pd.Timestamp(warm + "-01", tz="UTC")).total_seconds())
        out[off + warm_s: off + len(u)] = u[warm_s:]
        del u
        gc.collect()
    return out


def daily_markout(t: np.ndarray, px: np.ndarray, side: np.ndarray, horizon_ms: int = 10_000):
    """Per trade: aggressor side x price change over the next 10 s (bp). Returns (day, value)."""
    j = np.searchsorted(t, t + horizon_ms, side="right") - 1
    v = side * (px[j] - px) / px * 1e4
    day = (t - int(START.timestamp() * 1000)) // 86_400_000
    return day, v


@njit(cache=True)
def _fills(rule, improved, is_bid, p, q):
    if rule == 2:
        rule = 0 if improved else 1
    if is_bid:
        return p <= q if rule == 0 else p < q
    return p >= q if rule == 0 else p > q


@njit(cache=True)
def simulate_x(t, px, side, u, need_bp_day, start_ms, rule, u_on, exit_u, liquidate,
               delay, timeout, maker_bp, taker_bp):
    """Prices in whole ticks. Returns (entry_ms, pnl_bp_net, by_tp, improved_entry) per trip."""
    n = len(t)
    cap = n // 2 + 1
    ent_t = np.empty(cap, dtype=np.int64)
    pnl = np.empty(cap)
    by_tp = np.empty(cap, dtype=np.bool_)
    imp_e = np.empty(cap, dtype=np.bool_)
    k = 0
    bid_m = np.nan
    ask_m = np.nan
    q_bid = np.nan
    q_ask = np.nan
    q_imp = False
    p_bid = np.nan
    p_ask = np.nan
    p_imp = False
    p_time = -1
    pos = 0
    entry = 0.0
    entry_t = 0
    entry_imp = False
    tp = np.nan
    tp_imp = False
    tp_time = 0
    n_u = len(u)
    n_need = len(need_bp_day)
    for i in range(n):
        ti = t[i]
        p = px[i]
        s = side[i]
        sec = (ti - start_ms) // 1000 - 1
        ui = u[sec] if 0 <= sec < n_u else np.nan
        dd = (ti - start_ms) // 86_400_000
        need = need_bp_day[dd] if 0 <= dd < n_need else np.nan
        if p_time >= 0 and ti >= p_time:
            q_bid = p_bid
            q_ask = p_ask
            q_imp = p_imp
            p_time = -1
        if pos == 0:
            if s < 0 and q_bid == q_bid and _fills(rule, q_imp, True, p, q_bid):
                pos = 1
                entry = q_bid
                entry_imp = q_imp
            elif s > 0 and q_ask == q_ask and _fills(rule, q_imp, False, p, q_ask):
                pos = -1
                entry = q_ask
                entry_imp = q_imp
            if pos != 0:
                entry_t = ti
                nt = np.ceil(need * 1e-4 * entry) if need == need else 1.0
                nt = max(nt, 1.0)
                if pos > 0:
                    opp = ask_m - 1.0 if ask_m == ask_m else entry + nt
                    tp = max(entry + nt, opp)
                    tp_imp = ask_m == ask_m and tp < ask_m
                else:
                    opp = bid_m + 1.0 if bid_m == bid_m else entry - nt
                    tp = min(entry - nt, opp)
                    tp_imp = bid_m == bid_m and tp > bid_m
                tp_time = ti + delay
                q_bid = np.nan
                q_ask = np.nan
                p_time = -1
        else:
            closed = False
            if ti >= tp_time:
                if pos > 0 and s > 0 and _fills(rule, tp_imp, False, p, tp):
                    pnl[k] = (tp - entry) / entry * 1e4 - 2.0 * maker_bp
                    closed = True
                    by_tp[k] = True
                elif pos < 0 and s < 0 and _fills(rule, tp_imp, True, p, tp):
                    pnl[k] = (entry - tp) / entry * 1e4 - 2.0 * maker_bp
                    closed = True
                    by_tp[k] = True
            if not closed:
                band_out = liquidate and ui == ui and ui >= exit_u
                if band_out or ti - entry_t >= timeout:
                    if pos > 0:
                        xp = bid_m if bid_m == bid_m else p
                        pnl[k] = (xp - entry) / entry * 1e4 - maker_bp - taker_bp
                    else:
                        xp = ask_m if ask_m == ask_m else p
                        pnl[k] = (entry - xp) / entry * 1e4 - maker_bp - taker_bp
                    closed = True
                    by_tp[k] = False
            if closed:
                ent_t[k] = entry_t
                imp_e[k] = entry_imp
                k += 1
                pos = 0
        if s < 0:
            bid_m = p
            if ask_m == ask_m and ask_m <= bid_m:
                ask_m = bid_m + 1.0
        else:
            ask_m = p
            if bid_m == bid_m and bid_m >= ask_m:
                bid_m = ask_m - 1.0
        if pos == 0:
            d_bid = np.nan
            d_ask = np.nan
            d_imp = False
            allow = ui == ui and ui < u_on and ui < exit_u and need == need \
                and bid_m == bid_m and ask_m == ask_m
            if allow:
                spr = ask_m - bid_m
                if spr >= 3.0:
                    b_, a_, d_imp = bid_m + 1.0, ask_m - 1.0, True
                else:
                    b_, a_, d_imp = bid_m, ask_m, False
                mid = 0.5 * (b_ + a_)
                if (a_ - b_) / mid * 1e4 >= need:
                    d_bid = b_
                    d_ask = a_
            same = ((d_bid == q_bid) or (d_bid != d_bid and q_bid != q_bid)) and \
                   ((d_ask == q_ask) or (d_ask != d_ask and q_ask != q_ask))
            if not same:
                if p_time < 0:
                    p_time = ti + delay
                p_bid = d_bid
                p_ask = d_ask
                p_imp = d_imp
    if pos != 0:
        if pos > 0:
            pnl[k] = (bid_m - entry) / entry * 1e4 - maker_bp - taker_bp
        else:
            pnl[k] = (entry - ask_m) / entry * 1e4 - maker_bp - taker_bp
        by_tp[k] = False
        ent_t[k] = entry_t
        imp_e[k] = entry_imp
        k += 1
    return ent_t[:k], pnl[:k], by_tp[:k], imp_e[:k]


MULTS = (1000, 100, 10, 5, 2)
MULT_MIN_TRADES = 200


def effective_mult(t: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Per trade: the multiple of today's tick in force that UTC day, i.e. the largest m in MULTS
    with >= 99% of the day's prices (k, in today's ticks) on the m grid. A day with fewer than
    MULT_MIN_TRADES trades takes the previous day's value."""
    day = t // 86_400_000
    edges = np.flatnonzero(np.r_[True, day[1:] != day[:-1], True])
    out = np.ones(len(t), dtype=np.int64)
    prev = 1
    for a, b in zip(edges[:-1], edges[1:]):
        m = prev
        if b - a >= MULT_MIN_TRADES:
            m = 1
            for c in MULTS:
                if np.mean(k[a:b] % c == 0) >= 0.99:
                    m = c
                    break
        out[a:b] = m
        prev = m
    return out


def need_by_day(sym: str, tick: float) -> np.ndarray:
    """need[d] = 2 x maker + max(0, mean 10 s markout over days d-7..d-1)."""
    n_days = n_seconds() // E.DAY_S
    s = np.zeros(n_days)
    c = np.zeros(n_days)
    for mo in available(sym):
        tb = pq.read_table(E.trade_path(sym, mo), columns=["t", "px", "buyer_maker"])
        t = tb.column("t").to_numpy()
        px = tb.column("px").to_numpy()
        side = np.where(tb.column("buyer_maker").to_numpy(), -1.0, 1.0)
        del tb
        day, v = daily_markout(t, px, side)
        ok = (day >= 0) & (day < n_days)
        s += np.bincount(day[ok], v[ok], minlength=n_days)
        c += np.bincount(day[ok], minlength=n_days)
        del t, px, side, day, v
    daily = np.where(c > 0, s / np.maximum(c, 1), np.nan)
    trail = pd.Series(daily).rolling(AS_LOOKBACK_D, min_periods=AS_LOOKBACK_D).mean().shift(1).to_numpy()
    return 2 * MAKER_BP + np.maximum(trail, 0.0)


def build(sym: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{sym}.parquet"
    if p.exists():
        return
    tick = ticks()[sym]
    have = available(sym)
    sim = [m for m in SIM_MONTHS if m in have]
    if not sim:
        log.warning("%s: not listed in this period", sym)
        return
    need = need_by_day(sym, tick)
    us = {R: u_series(sym, R) for R in RS}
    start_ms = int(START.timestamp() * 1000)
    rows = []
    skipped = []
    for mo in sim:
        tb = pq.read_table(E.trade_path(sym, mo), columns=["t", "px", "buyer_maker"])
        t = tb.column("t").to_numpy()
        raw = tb.column("px").to_numpy() / tick
        px = np.rint(raw)
        off_grid = float(np.mean(np.abs(raw - px) > 1e-6))
        del raw
        if off_grid > 0.01:                     # the tick size was different in this month
            log.warning("%s %s: %.1f%% of prices off today's tick grid; month skipped", sym, mo, 100 * off_grid)
            skipped.append(mo)
            continue
        side = np.where(tb.column("buyer_maker").to_numpy(), -1, 1).astype(np.int8)
        del tb
        # the exchange tick was coarser in the past for many coins: simulate each run of days in
        # units of the tick actually in force (trades show it), not today's tick
        mult = effective_mult(t, px.astype(np.int64))
        cuts = np.flatnonzero(np.diff(mult)) + 1
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(t)]):
            m = float(mult[a])
            ts, ps, ss = t[a:b], np.rint(px[a:b] / m), side[a:b]
            for R in RS:
                for rname, r in RULES.items():
                    for uo in U_ON:
                        for lname, lq in LIQUIDATE.items():
                            if R == 5 and (rname != "hybrid" or uo != 0.8 or lname != "hold"):
                                continue                      # R = 5 only for the primary settings
                            et, pl, tp, im = simulate_x(ts, ps, ss, us[R], need, start_ms, r, uo, EXIT_U, lq,
                                                        DELAY_MS, TIMEOUT_MS, MAKER_BP, TAKER_BP)
                            rows.append(pd.DataFrame({"R": R, "rule": rname, "u_on": uo, "exit": lname, "t": et,
                                                      "pnl_bp": pl.astype(np.float32), "by_tp": tp, "improved": im,
                                                      "mult": np.int16(m)}))
        del t, px, side, mult
        gc.collect()
    if not rows:
        log.warning("%s: no usable month", sym)
        return
    df = pd.concat(rows, ignore_index=True)
    df["day"] = ((df["t"] - start_ms) // 86_400_000).astype(np.int32)
    # store daily aggregates only (disk budget); p01 is the daily 1st percentile of trip PnL
    g = df.groupby(["R", "rule", "u_on", "exit", "day"])
    agg = g["pnl_bp"].agg(["sum", "count"]).reset_index()
    agg["n_tp"] = g["by_tp"].sum().to_numpy()
    agg["n_improved"] = g["improved"].sum().to_numpy()
    agg["p01"] = g["pnl_bp"].quantile(0.01).to_numpy()
    agg["mult"] = g["mult"].max().to_numpy()
    agg["skipped_months"] = ",".join(skipped)
    agg.to_parquet(p)
    log.info("%s: %d trips (all variants), %d skipped months", sym, len(df), len(skipped))


def daily_table() -> pd.DataFrame:
    frames = []
    for f in sorted(OUT.glob("*.parquet")):
        g = pd.read_parquet(f, columns=KEYS + ["day", "sum", "count", "n_tp", "n_improved"])
        g["sym"] = f.stem
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def select(daily: pd.DataFrame) -> pd.DataFrame:
    """Mark (sym, day) active from the previous SEL_LOOKBACK_D days only."""
    out = []
    for key, x in daily.groupby(KEYS + ["sym"]):
        x = (x[["day", "sum", "count", "n_tp", "n_improved"]].set_index("day")
             .reindex(range(daily["day"].min(), daily["day"].max() + 1), fill_value=0))
        s = x["sum"].rolling(SEL_LOOKBACK_D, min_periods=1).sum().shift(1)
        n = x["count"].rolling(SEL_LOOKBACK_D, min_periods=1).sum().shift(1)
        x["active"] = (n >= SEL_MIN_TRIPS) & (s / n.where(n > 0) > 0)
        x = x.reset_index().rename(columns={"index": "day"})
        for k_, v in zip(KEYS + ["sym"], key):
            x[k_] = v
        out.append(x)
    return pd.concat(out, ignore_index=True)


def summary(n_random: int = 200, seed: int = 0) -> pd.DataFrame:
    daily = select(daily_table())
    first_sim_day = int((pd.Timestamp(SIM_MONTHS[0] + "-01", tz="UTC") - START).days) + SEL_LOOKBACK_D
    daily = daily[daily["day"] >= first_sim_day]
    cut = int((pd.Timestamp(DESIGN_END + "-01", tz="UTC") - START).days)
    daily["half"] = np.where(daily["day"] < cut, HALVES[0], HALVES[1])
    if PERIOD != "main":
        daily = pd.concat([daily, daily.assign(half="whole")], ignore_index=True)
    rng = np.random.default_rng(seed)
    rows = []
    for key, x in daily.groupby(KEYS + ["half"]):
        for book, xb in (("all", x), ("selected", x[x["active"]])):
            dv = xb.groupby("day")[["sum", "count"]].sum().rename(columns={"count": "n"})
            lo, hi = block_ci(dv)
            row = dict(zip(KEYS + ["half"], key))
            row.update({"book": book, "trips": int(dv["n"].sum()), "trips_per_day": dv["n"].mean(),
                        "syms_per_day": xb.groupby("day")["sym"].nunique().mean(),
                        "pnl_per_trip_bp": dv["sum"].sum() / max(dv["n"].sum(), 1), "ci_lo": lo, "ci_hi": hi})
            if book == "selected":
                # random books: the same number of symbols per day, drawn from symbols with trips that day
                k_by_day = xb.groupby("day")["sym"].nunique()
                pool = {d: g[g["count"] > 0] for d, g in x.groupby("day")}
                vals = []
                for _ in range(n_random):
                    s_ = n_ = 0.0
                    for d, kd in k_by_day.items():
                        g = pool.get(d)
                        if g is None or not len(g):
                            continue
                        pick = g.iloc[rng.choice(len(g), min(kd, len(g)), replace=False)]
                        s_ += pick["sum"].sum()
                        n_ += pick["count"].sum()
                    vals.append(s_ / max(n_, 1))
                row["random_mean"], row["random_p95"] = float(np.mean(vals)), float(np.percentile(vals, 95))
            rows.append(row)
    out = pd.DataFrame(rows)
    tag = "" if PERIOD == "main" else "_" + PERIOD
    out.to_csv(RES / f"summary_{NAME}{tag}.csv", index=False)
    per_sym = daily.groupby(KEYS + ["half", "sym"])[["sum", "count"]].sum().reset_index()
    per_sym["pnl_per_trip_bp"] = per_sym["sum"] / per_sym["count"].clip(lower=1)
    per_sym.to_csv(RES / f"summary_{NAME}{tag}_by_symbol.csv", index=False)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "summary"])
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--period", choices=list(PERIODS), default="main")
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    set_period(a.period)
    if a.cmd == "build":
        syms = a.symbols or pd.read_csv(UNIVERSE)["sym"].tolist()
        for s in syms:
            try:
                build(s)
            except FileNotFoundError as e:
                log.warning("%s: missing data (%s)", s, e)
    else:
        pd.set_option("display.width", 250)
        print(summary().round(3).to_string(index=False))


if __name__ == "__main__":
    main()
