"""Stage P, part 1: features of each stage X primary round trip at its decision time (DESIGN.md).

    python -m mm_tick.toxic build          # 2026 period -> results/toxic_features.parquet

Decision time tau = fill time - 250 ms; only trades strictly before tau are used. Direction
features are signed by the trip side d (+1 long, -1 short): > 0 is in favour of the position.
"""
from __future__ import annotations

import argparse
import gc
import logging

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import events as E
from . import grid as G
from . import xs
from .run import RES, ticks

OUT = RES / "toxic_features.parquet"
W_RET = (1, 5, 30, 120, 600)            # seconds
W_CNT = (5, 30, 120)
W_PATH = (30, 120, 600)
log = logging.getLogger("mm_tick.toxic")


def window_features(t, lp, side, notional, tau, d) -> dict:
    """Vectorised features at decision times tau (ms) from trades (t sorted, lp = log price)."""
    buy = np.where(side > 0, notional, 0.0)
    sell = np.where(side < 0, notional, 0.0)
    cb = np.r_[0.0, np.cumsum(buy)]
    cs = np.r_[0.0, np.cumsum(sell)]
    cpath = np.r_[0.0, np.cumsum(np.abs(np.diff(lp, prepend=lp[0])))]
    now = np.searchsorted(t, tau, side="left")            # trades [0, now) are before tau
    ok = now > 0
    last = np.maximum(now - 1, 0)
    p_now = np.where(ok, lp[last], np.nan)
    f = {}

    def start(w_ms):
        return np.searchsorted(t, tau - w_ms, side="left")

    for w in W_RET:
        a = start(w * 1000)
        p_a = np.where(a > 0, lp[np.maximum(a - 1, 0)], np.nan)         # last price before tau - W
        f[f"ret_{w}s"] = d * (p_now - p_a) * 1e4
        b_, s_ = cb[now] - cb[a], cs[now] - cs[a]
        tot = b_ + s_
        f[f"ofi_{w}s"] = np.where(tot > 0, d * (b_ - s_) / np.where(tot > 0, tot, 1), 0.0)
    a_h = start(3_600_000)
    per_ms_h = (now - a_h) / 3_600_000
    for w in W_CNT:
        a = start(w * 1000)
        f[f"cnt_{w}s"] = np.where(per_ms_h > 0, (now - a) / np.where(per_ms_h > 0, per_ms_h * w * 1000, 1), np.nan)
    for w in W_PATH:
        a = start(w * 1000)
        f[f"path_{w}s"] = (cpath[now] - cpath[a]) * 1e4
    a10 = start(600_000)
    tot10 = (cb[now] - cb[a10]) + (cs[now] - cs[a10])
    n10 = now - a10
    mean10 = np.where(n10 > 0, tot10 / np.maximum(n10, 1), np.nan)
    f["size_rel"] = np.where(ok, notional[last] / mean10, np.nan)
    f["log_dt_last"] = np.where(ok, np.log1p(np.maximum(tau - t[last], 0)), np.nan)
    # estimated touch from the last taker sell (bid) and taker buy (ask) before tau
    for nm, sgn in (("bid", -1), ("ask", 1)):
        idx = np.flatnonzero(side == sgn)
        if not len(idx):
            f["_" + nm] = np.full(len(tau), np.nan)
            continue
        j = np.searchsorted(t[idx], tau, side="left") - 1
        f["_" + nm] = np.where(j >= 0, lp[idx[np.maximum(j, 0)]], np.nan)
    return f


def build_symbol(sym: str) -> pd.DataFrame | None:
    tick = ticks()[sym]
    sim = [m for m in xs.SIM_MONTHS if m in xs.available(sym)]
    if not sim:
        return None
    need = xs.need_by_day(sym, tick)
    u = xs.u_series(sym, 15)
    anchor, den, _ = G.band_series(sym)
    start_ms = int(xs.START.timestamp() * 1000)
    frames = []
    for mo in sim:
        tb = pq.read_table(E.trade_path(sym, mo), columns=["t", "px", "qty", "buyer_maker"])
        t = tb.column("t").to_numpy()
        price = tb.column("px").to_numpy()
        raw = price / tick
        px = np.rint(raw)
        if float(np.mean(np.abs(raw - px) > 1e-6)) > 0.01:
            continue
        del raw
        notional = price * tb.column("qty").to_numpy()
        side = np.where(tb.column("buyer_maker").to_numpy(), -1, 1).astype(np.int8)
        del tb
        mult = xs.effective_mult(t, px.astype(np.int64))
        cuts = np.flatnonzero(np.diff(mult)) + 1
        trips = []
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(t)]):
            m = float(mult[a])
            et, pl, tp, im, sd = xs.simulate_x(t[a:b], np.rint(px[a:b] / m), side[a:b], u, need, start_ms,
                                               xs.RULES["hybrid"], 0.8, xs.EXIT_U, False,
                                               xs.DELAY_MS, xs.TIMEOUT_MS, xs.MAKER_BP, xs.TAKER_BP)
            trips.append(pd.DataFrame({"t": et, "pnl_bp": pl.astype(np.float32), "by_tp": tp,
                                       "improved": im, "d": sd, "tick_mult": m}))
        tr = pd.concat(trips, ignore_index=True)
        if not len(tr):
            continue
        tau = tr["t"].to_numpy() - xs.DELAY_MS
        d = tr["d"].to_numpy().astype(np.float64)
        lp = np.log(price)
        f = window_features(t, lp, side, notional, tau, d)
        tr["spread_ticks"] = (np.exp(f.pop("_ask")) - np.exp(f.pop("_bid"))) / (tick * tr["tick_mult"].to_numpy())
        for k, v in f.items():
            tr[k] = v.astype(np.float32)
        sec = (tau - start_ms) // 1000 - 1
        oks = (sec >= 0) & (sec < len(u))
        sec_c = np.clip(sec, 0, len(u) - 1)
        tr["u"] = np.where(oks, u[sec_c], np.nan).astype(np.float32)
        last = np.maximum(np.searchsorted(t, tau, side="left") - 1, 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = (lp[last] - anchor[sec_c]) / den[sec_c]
        tr["dz"] = np.where(oks, d * z, np.nan).astype(np.float32)
        day = (tau - start_ms) // 86_400_000
        tr["need"] = need[np.clip(day, 0, len(need) - 1)].astype(np.float32)
        tr["tick_bp"] = (tick * tr["tick_mult"].to_numpy() / price[last] * 1e4).astype(np.float32)
        hour = ((tau // 1000) % 86_400) / 3600.0
        tr["hour_sin"] = np.sin(2 * np.pi * hour / 24).astype(np.float32)
        tr["hour_cos"] = np.cos(2 * np.pi * hour / 24).astype(np.float32)
        frames.append(tr)
        del t, price, px, notional, side, mult, lp
        gc.collect()
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["sym"] = sym
    return df


def build() -> None:
    xs.set_period("main")
    part = RES / "toxic_parts"
    part.mkdir(exist_ok=True)
    for s in pd.read_csv(xs.UNIVERSE)["sym"]:
        p = part / f"{s}.parquet"
        if p.exists():
            continue
        try:
            d = build_symbol(s)
        except FileNotFoundError:
            d = None
        if d is not None:
            d.to_parquet(p)
            log.info("%s: %d trips", s, len(d))
    df = pd.concat([pd.read_parquet(p) for p in sorted(part.glob("*.parquet"))], ignore_index=True)
    start_ms = int(xs.START.timestamp() * 1000)
    df["day"] = ((df["t"] - start_ms) // 86_400_000).astype(np.int32)
    first = int((pd.Timestamp(xs.SIM_MONTHS[0] + "-01", tz="UTC") - xs.START).days) + xs.SEL_LOOKBACK_D
    df = df[df["day"] >= first].copy()
    df["y"] = (df["pnl_bp"] < 0).astype(np.int8)
    # the coin's loss share over days d-8..d-2: a trip of day d-1 can still be open at the start of
    # day d (30 min timeout), so day d-1 is left out to keep every label resolved before use
    g = df.groupby(["sym", "day"])["y"].agg(["sum", "count"]).reset_index()
    out = []
    for s, x in g.groupby("sym"):
        x = x.set_index("day")[["sum", "count"]].reindex(range(g["day"].min(), g["day"].max() + 1), fill_value=0)
        ls = x["sum"].rolling(7, min_periods=1).sum().shift(2) / x["count"].rolling(7, min_periods=1).sum().shift(2)
        out.append(pd.DataFrame({"sym": s, "day": x.index, "loss7": ls.to_numpy()}))
    df = df.merge(pd.concat(out), on=["sym", "day"], how="left")
    df["loss7"] = df["loss7"].astype(np.float32)
    df["month"] = (xs.START + pd.to_timedelta(df["day"], unit="D")).dt.strftime("%Y-%m")
    df.to_parquet(OUT)
    log.info("features: %d trips, %d columns", len(df), df.shape[1])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    build()


if __name__ == "__main__":
    main()
