"""Stage G: band-bounded inventory maker on Binance USDT-M, simulated on trades (see DESIGN.md).

    python -m mm_tick.grid build   --period main|early
    python -m mm_tick.grid summary --period main|early

Reuses the stage X machinery: universe, periods, need (2 x maker + trailing markout), the tick in
force per day, the monitoring rule and the summary with random books.
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
from . import xs
from .anchored import anchored_z
from .revert import cdf_by_day
from .run import RES, ticks
from .xs import _fills

R_MIN = 15
Q_BAND = 0.8
Q_BREAKS = (0.8, 0.99)          # 0.8: break at the band edge (primary); 0.99: variant
MAX_INV = (5, 1)                # 5 units (primary); 1: no build-up
RULES = {"hybrid": 2, "through": 1}
KEYS = ["rule", "brk", "inv"]
log = logging.getLogger("mm_tick.grid")

EXIT_MAKER, EXIT_BREAK, EXIT_END = 0, 1, 2


def _zq(cdf: np.ndarray, q: float) -> np.ndarray:
    """Per day: the q point of |z| over the previous 14 days (upper bin edge), NaN early."""
    ok = np.isfinite(cdf[:, 0])
    b = np.argmax(cdf >= q, axis=1)
    out = E.EDGES[b + 1].astype(np.float64)
    out[~ok] = np.nan
    return out


def band_series(sym: str):
    """Per second over the period: log anchor (float64) and scale den (float32); per day: the
    band and break quantiles of |z|. Built in chunks of up to 3 months plus a warm-up month."""
    n = xs.n_seconds()
    n_days = n // E.DAY_S
    anchor = np.full(n, np.nan)
    den = np.full(n, np.nan, dtype=np.float32)
    zq = {q: np.full(n_days, np.nan) for q in (Q_BAND,) + Q_BREAKS}
    for c in range(0, len(xs.SIM_MONTHS), 3):
        target = xs.SIM_MONTHS[c:c + 3]
        warm = xs.MONTHS[xs.MONTHS.index(target[0]) - 1]
        months = [warm] + target
        g = E.second_grid(sym, months, allow_missing=True)
        px = g["px"]
        del g
        az = anchored_z(px, R_MIN, full=True)
        del px
        cdf = cdf_by_day(az["z"], az["n_days"])
        off = int((pd.Timestamp(months[0] + "-01", tz="UTC") - xs.START).total_seconds())
        warm_s = int((pd.Timestamp(target[0] + "-01", tz="UTC") - pd.Timestamp(warm + "-01", tz="UTC")).total_seconds())
        m = len(az["den"])
        anchor[off + warm_s: off + m] = az["anchor"][warm_s:]
        den[off + warm_s: off + m] = az["den"][warm_s:]
        d0, wd = off // E.DAY_S, warm_s // E.DAY_S
        for q in zq:
            v = _zq(cdf, q)
            zq[q][d0 + wd: d0 + len(v)] = v[wd:]
        del az, cdf
        gc.collect()
    return anchor, den, zq


@njit(cache=True)
def simulate_g(t, px, side, anchor, den, zq_band, zq_brk, need_day, start_ms, unit, rule, max_inv,
               delay, maker_bp, taker_bp):
    """Prices in units of the tick in force (`unit` = that tick in price). Returns, per closed
    unit: (entry_ms, pnl_bp_net, exit_kind, inventory_after_entry)."""
    n = len(t)
    cap = n + max_inv + 1
    ent_t = np.empty(cap, dtype=np.int64)
    pnl = np.empty(cap)
    kind = np.empty(cap, dtype=np.int8)
    inv_e = np.empty(cap, dtype=np.int8)
    k = 0
    e_px = np.zeros(max_inv)          # open units, oldest first
    e_tm = np.zeros(max_inv, dtype=np.int64)
    e_inv = np.zeros(max_inv, dtype=np.int8)
    m_open = 0
    pos = 0                           # signed units
    last_e = np.nan
    bid_m = np.nan
    ask_m = np.nan
    q_bid = np.nan
    q_ask = np.nan
    q_bimp = False
    q_aimp = False
    p_bid = np.nan
    p_ask = np.nan
    p_bimp = False
    p_aimp = False
    p_time = -1
    n_a = len(anchor)
    n_d = len(need_day)
    n_z = len(zq_band)
    for i in range(n):
        ti = t[i]
        p = px[i]
        s = side[i]
        sec = (ti - start_ms) // 1000 - 1
        dd = (ti - start_ms) // 86_400_000
        need = need_day[dd] if 0 <= dd < n_d else np.nan
        if p_time >= 0 and ti >= p_time:
            q_bid = p_bid
            q_ask = p_ask
            q_bimp = p_bimp
            q_aimp = p_aimp
            p_time = -1
        # 1) fills (one unit per trade)
        fill = np.nan
        if s < 0 and q_bid == q_bid and _fills(rule, q_bimp, True, p, q_bid):
            fill = q_bid
            q_bid = np.nan
            p_time = -1                                  # an update decided before the fill is stale
            if pos < 0:                                  # buy back the oldest short unit
                e = e_px[0]
                ent_t[k] = e_tm[0]
                pnl[k] = (e - fill) / e * 1e4 - 2.0 * maker_bp
                kind[k] = 0
                inv_e[k] = e_inv[0]
                k += 1
                for j in range(m_open - 1):
                    e_px[j] = e_px[j + 1]
                    e_tm[j] = e_tm[j + 1]
                    e_inv[j] = e_inv[j + 1]
                m_open -= 1
                pos += 1
            else:
                e_px[m_open] = fill
                e_tm[m_open] = ti
                pos += 1
                e_inv[m_open] = pos
                m_open += 1
                last_e = fill
        elif s > 0 and q_ask == q_ask and _fills(rule, q_aimp, False, p, q_ask):
            fill = q_ask
            q_ask = np.nan
            p_time = -1
            if pos > 0:                                  # sell the oldest long unit
                e = e_px[0]
                ent_t[k] = e_tm[0]
                pnl[k] = (fill - e) / e * 1e4 - 2.0 * maker_bp
                kind[k] = 0
                inv_e[k] = e_inv[0]
                k += 1
                for j in range(m_open - 1):
                    e_px[j] = e_px[j + 1]
                    e_tm[j] = e_tm[j + 1]
                    e_inv[j] = e_inv[j + 1]
                m_open -= 1
                pos -= 1
            else:
                e_px[m_open] = fill
                e_tm[m_open] = ti
                pos -= 1
                e_inv[m_open] = -pos
                m_open += 1
                last_e = fill
        # 2) market estimate from this trade
        if s < 0:
            bid_m = p
            if ask_m == ask_m and ask_m <= bid_m:
                ask_m = bid_m + 1.0
        else:
            ask_m = p
            if bid_m == bid_m and bid_m >= ask_m:
                bid_m = ask_m - 1.0
        # 3) band and break levels for this second
        a = anchor[sec] if 0 <= sec < n_a else np.nan
        dn = den[sec] if 0 <= sec < n_a else np.nan
        zb = zq_band[sec // 86_400] if 0 <= sec < n_a and sec // 86_400 < n_z else np.nan
        zk = zq_brk[sec // 86_400] if 0 <= sec < n_a and sec // 86_400 < n_z else np.nan
        valid = a == a and dn == dn and zb == zb and zk == zk
        lo_t = np.nan
        hi_t = np.nan
        if valid:
            lo_t = np.ceil(np.exp(a - zb * dn) / unit)
            hi_t = np.floor(np.exp(a + zb * dn) / unit)
            b_lo = np.exp(a - zk * dn) / unit
            b_hi = np.exp(a + zk * dn) / unit
            brk = (pos > 0 and p < b_lo and bid_m == bid_m) or (pos < 0 and p > b_hi and ask_m == ask_m)
            if brk:
                xp = bid_m if pos > 0 else ask_m
                for j in range(m_open):
                    e = e_px[j]
                    ent_t[k] = e_tm[j]
                    pnl[k] = ((xp - e) if pos > 0 else (e - xp)) / e * 1e4 - maker_bp - taker_bp
                    kind[k] = 1
                    inv_e[k] = e_inv[j]
                    k += 1
                m_open = 0
                pos = 0
                last_e = np.nan
                q_bid = np.nan                # resting orders are cancelled with the liquidation
                q_ask = np.nan
                p_time = -1
        # 4) desired quotes
        d_bid = np.nan
        d_ask = np.nan
        d_bimp = False
        d_aimp = False
        if bid_m == bid_m and ask_m == ask_m and need == need:
            mid = 0.5 * (bid_m + ask_m)
            nt = max(1.0, np.ceil(need * 1e-4 * mid))
            if ask_m - bid_m >= 3.0:
                b_ = bid_m + 1.0
                a_ = ask_m - 1.0
            else:
                b_ = bid_m
                a_ = ask_m
            inside = valid and lo_t <= p <= hi_t
            avg = 0.0
            for j in range(m_open):
                avg += e_px[j]
            avg = avg / m_open if m_open > 0 else np.nan
            # bid side: exit a short, or enter / add long
            if pos < 0:
                x = min(b_, np.floor(avg - nt))              # prices stay on the tick grid
                if valid:
                    x = max(x, lo_t)
                x = min(x, ask_m - 1.0)
                d_bid = x
            elif pos < max_inv and inside:
                x = max(b_, lo_t)
                if pos > 0 and x > last_e - nt:
                    x = last_e - nt
                if x >= lo_t and x <= ask_m - 1.0 and hi_t - x >= nt:
                    d_bid = x
            # ask side: exit a long, or enter / add short
            if pos > 0:
                x = max(a_, np.ceil(avg + nt))
                if valid:
                    x = min(x, hi_t)
                x = max(x, bid_m + 1.0)
                d_ask = x
            elif pos > -max_inv and inside:
                x = min(a_, hi_t)
                if pos < 0 and x < last_e + nt:
                    x = last_e + nt
                if x <= hi_t and x >= bid_m + 1.0 and x - lo_t >= nt:
                    d_ask = x
            d_bimp = d_bid == d_bid and d_bid > bid_m
            d_aimp = d_ask == d_ask and d_ask < ask_m
        same = ((d_bid == q_bid) or (d_bid != d_bid and q_bid != q_bid)) and \
               ((d_ask == q_ask) or (d_ask != d_ask and q_ask != q_ask))
        if not same:
            if p_time < 0:
                p_time = ti + delay
            p_bid = d_bid
            p_ask = d_ask
            p_bimp = d_bimp
            p_aimp = d_aimp
    # close what is left at the end of the segment, by taker
    if m_open > 0:
        xp = bid_m if pos > 0 else ask_m
        for j in range(m_open):
            e = e_px[j]
            ent_t[k] = e_tm[j]
            pnl[k] = ((xp - e) if pos > 0 else (e - xp)) / e * 1e4 - maker_bp - taker_bp
            kind[k] = 2
            inv_e[k] = e_inv[j]
            k += 1
    return ent_t[:k], pnl[:k], kind[:k], inv_e[:k]


def out_dir():
    return RES / ("grid_" + xs.PERIOD)


def build(sym: str) -> None:
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{sym}.parquet"
    if p.exists():
        return
    tick = ticks()[sym]
    have = xs.available(sym)
    sim = [m for m in xs.SIM_MONTHS if m in have]
    if not sim:
        log.warning("%s: not listed in this period", sym)
        return
    need = xs.need_by_day(sym, tick)
    anchor, den, zq = band_series(sym)
    start_ms = int(xs.START.timestamp() * 1000)
    rows, skipped = [], []
    for mo in sim:
        tb = pq.read_table(E.trade_path(sym, mo), columns=["t", "px", "buyer_maker"])
        t = tb.column("t").to_numpy()
        raw = tb.column("px").to_numpy() / tick
        px = np.rint(raw)
        off_grid = float(np.mean(np.abs(raw - px) > 1e-6))
        del raw
        if off_grid > 0.01:
            log.warning("%s %s: %.1f%% of prices off today's tick grid; month skipped", sym, mo, 100 * off_grid)
            skipped.append(mo)
            continue
        side = np.where(tb.column("buyer_maker").to_numpy(), -1, 1).astype(np.int8)
        del tb
        mult = xs.effective_mult(t, px.astype(np.int64))
        cuts = np.flatnonzero(np.diff(mult)) + 1
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(t)]):
            m = float(mult[a])
            ts, ps, ss = t[a:b], np.rint(px[a:b] / m), side[a:b]
            for rname, r in RULES.items():
                for qb in Q_BREAKS:
                    for inv in MAX_INV:
                        if rname != "hybrid" and (qb != Q_BREAKS[0] or inv != MAX_INV[0]):
                            continue                       # the through rule only at the primary
                        et, pl, kd, ie = simulate_g(ts, ps, ss, anchor, den, zq[Q_BAND], zq[qb], need, start_ms,
                                                    tick * m, r, inv, xs.DELAY_MS, xs.MAKER_BP, xs.TAKER_BP)
                        rows.append(pd.DataFrame({"rule": rname, "brk": qb, "inv": inv, "t": et,
                                                  "pnl_bp": pl.astype(np.float32), "kind": kd, "inv_e": ie}))
        del t, px, side, mult
        gc.collect()
    if not rows:
        log.warning("%s: no usable month", sym)
        return
    df = pd.concat(rows, ignore_index=True)
    df["day"] = ((df["t"] - start_ms) // 86_400_000).astype(np.int32)
    g = df.groupby(KEYS + ["day"])
    agg = g["pnl_bp"].agg(["sum", "count"]).reset_index()
    agg["n_tp"] = g["kind"].apply(lambda v: int((v == EXIT_MAKER).sum())).to_numpy()       # maker exits
    agg["n_improved"] = g["kind"].apply(lambda v: int((v == EXIT_BREAK).sum())).to_numpy()  # break exits
    agg["n_end"] = g["kind"].apply(lambda v: int((v == EXIT_END).sum())).to_numpy()
    agg["max_inv_e"] = g["inv_e"].max().to_numpy()
    agg["p01"] = g["pnl_bp"].quantile(0.01).to_numpy()
    agg["skipped_months"] = ",".join(skipped)
    agg.to_parquet(p)
    log.info("%s: %d closed units (all variants), %d skipped months", sym, len(df), len(skipped))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "summary"])
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--period", choices=list(xs.PERIODS), default="main")
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    xs.set_period(a.period)
    if a.cmd == "build":
        syms = a.symbols or pd.read_csv(xs.UNIVERSE)["sym"].tolist()
        for s in syms:
            try:
                build(s)
            except FileNotFoundError as e:
                log.warning("%s: missing data (%s)", s, e)
    else:
        xs.KEYS, xs.NAME, xs.OUT = KEYS, "grid", out_dir()
        pd.set_option("display.width", 250)
        print(xs.summary().round(3).to_string(index=False))


if __name__ == "__main__":
    main()
