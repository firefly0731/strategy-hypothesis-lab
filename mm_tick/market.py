"""Stage N: per-second market series from every universe coin (DESIGN.md).

    python -m mm_tick.market build [--period main]   # -> results/market_<period>.npz

Second s holds what is known at its start (trades strictly before it):
  M[s]     cumulative equal-weight mean of the coins' 1-s log returns
  br5/br30 (coins up - coins down) / coins with a price, over the last 5 / 30 s
  tb[s]    all coins' trades before second s (cumulative count)
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import events as E
from . import xs
from .run import RES

MKT = ["mkt_ret_1s", "mkt_ret_5s", "mkt_ret_30s", "mkt_ret_120s", "mkt_ret_600s",
       "mkt_br_5s", "mkt_br_30s", "mkt_act_5s", "mkt_act_30s", "rel_ret_30s"]
MKT_SIGNED = [f for f in MKT if not f.startswith("mkt_act")]
log = logging.getLogger("mm_tick.market")


def path(period: str):
    return RES / f"market_{period}.npz"


def coin_seconds(sym: str, n: int, start_ms: int):
    """Last log price before each second's start (NaN before the first trade) and trades per second."""
    lp = np.full(n, np.nan)
    cnt = np.zeros(n, dtype=np.int64)
    for mo in xs.available(sym):
        t = pq.read_table(E.trade_path(sym, mo), columns=["t"]).column("t").to_numpy()
        px = pq.read_table(E.trade_path(sym, mo), columns=["px"]).column("px").to_numpy()
        s0 = max(int((t[0] - start_ms) // 1000), 0)
        s1 = min(int((t[-1] - start_ms) // 1000) + 2, n)
        starts = start_ms + np.arange(s0, s1, dtype=np.int64) * 1000
        j = np.searchsorted(t, starts, side="left") - 1
        ok = j >= 0
        seg = np.where(ok, np.log(px[np.maximum(j, 0)]), np.nan)
        lp[s0:s1] = np.where(np.isfinite(seg), seg, lp[s0:s1])
        sec = (t - start_ms) // 1000
        sec = sec[(sec >= 0) & (sec < n)]
        cnt += np.bincount(sec, minlength=n)
    # carry the last price across a gap between months (no trade = unchanged)
    s = pd.Series(lp).ffill().to_numpy()
    return s, cnt


def build(period: str) -> None:
    xs.set_period(period)
    n = xs.n_seconds()
    start_ms = int(xs.START.timestamp() * 1000)
    sum_r = np.zeros(n)
    n_r = np.zeros(n, dtype=np.int32)
    up = {w: np.zeros(n, dtype=np.int32) for w in (5, 30)}
    dn = {w: np.zeros(n, dtype=np.int32) for w in (5, 30)}
    nb = {w: np.zeros(n, dtype=np.int32) for w in (5, 30)}
    trades = np.zeros(n, dtype=np.int64)
    k = 0
    for sym in pd.read_csv(xs.UNIVERSE)["sym"]:
        if not xs.available(sym):
            continue
        lp, cnt = coin_seconds(sym, n, start_ms)
        r = np.r_[np.nan, np.diff(lp)]
        ok = np.isfinite(r)
        sum_r[ok] += r[ok]
        n_r += ok
        for w in (5, 30):
            rw = np.r_[np.full(w, np.nan), lp[w:] - lp[:-w]]
            f = np.isfinite(rw)
            up[w] += f & (rw > 0)
            dn[w] += f & (rw < 0)
            nb[w] += f
        trades += cnt
        k += 1
        log.info("%s done (%d)", sym, k)
    mret = np.where(n_r > 0, sum_r / np.maximum(n_r, 1), 0.0)
    M = np.cumsum(mret)
    tb = np.r_[0, np.cumsum(trades)[:-1]]                # trades strictly before second s
    br = {w: np.where(nb[w] > 0, (up[w] - dn[w]) / np.maximum(nb[w], 1), np.nan).astype(np.float32) for w in (5, 30)}
    np.savez(path(period), M=M.astype(np.float64), br5=br[5], br30=br[30], tb=tb, start_ms=start_ms, n_coins=k)
    log.info("market series: %d seconds, %d coins", n, k)


class Market:
    def __init__(self, period: str):
        z = np.load(path(period))
        self.M, self.br5, self.br30, self.tb = z["M"], z["br5"], z["br30"], z["tb"]
        self.start_ms = int(z["start_ms"])

    def features(self, sec: np.ndarray, d: np.ndarray, own_ret30: np.ndarray) -> dict:
        """sec = global second index (start of second); own_ret30 already signed by d (bp)."""
        n = len(self.M)
        ok = (sec >= 0) & (sec < n)
        s = np.clip(sec, 0, n - 1)
        f = {}
        for w in (1, 5, 30, 120, 600):
            a = s - w
            v = np.where(ok & (a >= 0), (self.M[s] - self.M[np.maximum(a, 0)]) * 1e4, np.nan)
            f[f"mkt_ret_{w}s"] = (d * v).astype(np.float32)
        f["mkt_br_5s"] = np.where(ok, d * self.br5[s], np.nan).astype(np.float32)
        f["mkt_br_30s"] = np.where(ok, d * self.br30[s], np.nan).astype(np.float32)
        h = np.maximum(s - 3600, 0)
        rate = (self.tb[s] - self.tb[h]) / np.maximum(s - h, 1)
        for w in (5, 30):
            a = np.maximum(s - w, 0)
            f[f"mkt_act_{w}s"] = np.where(ok & (rate > 0), (self.tb[s] - self.tb[a]) / np.maximum(rate * w, 1e-9),
                                          np.nan).astype(np.float32)
        f["rel_ret_30s"] = (own_ret30 - f["mkt_ret_30s"]).astype(np.float32)
        return f


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--period", default="main", choices=sorted(xs.PERIODS))
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    build(a.period)


if __name__ == "__main__":
    main()
