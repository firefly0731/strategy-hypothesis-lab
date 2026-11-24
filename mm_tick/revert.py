"""Stage R: first-passage reversion of a hypothetical grid fill (see DESIGN.md, Stage R).

    python -m mm_tick.revert build   --group discovery
    python -m mm_tick.revert summary --group discovery
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
from .anchored import RS_MIN, anchored_z
from .run import GROUPS, MONTHS, RES, block_ci, ticks

DELTAS_BP = (5, 10, 20)
U_BINS = (0.0, 0.5, 0.8, 0.9, 0.95, 0.99, 1.0000001)
HMAX_S = 900
STEP_S = 10
MIN_TAU = 10
log = logging.getLogger("mm_tick.revert")


def grid_hl(sym: str, months: list[str]) -> dict:
    """1-second grid: last price, trade high/low, side of the last trade, net taker flow."""
    first = pd.Timestamp(months[0] + "-01", tz="UTC")
    y, m = map(int, months[-1].split("-"))
    last = pd.Timestamp(year=y + (m == 12), month=1 if m == 12 else m + 1, day=1, tz="UTC")
    start_ms = int(first.timestamp() * 1000)
    n = int((last - first).total_seconds())
    px = np.full(n, np.nan)
    hi = np.full(n, np.nan, dtype=np.float32)
    lo = np.full(n, np.nan, dtype=np.float32)
    side = np.zeros(n, dtype=np.int8)
    net = np.zeros(n, dtype=np.float32)
    for mo in months:
        for batch in pq.ParquetFile(E.trade_path(sym, mo)).iter_batches(batch_size=4_000_000):
            df = batch.to_pandas()
            sec = (df["t"].to_numpy() - start_ms) // 1000
            ok = (sec >= 0) & (sec < n)
            sec = sec[ok]
            if not len(sec):
                continue
            p = df["px"].to_numpy()[ok]
            bm = df["buyer_maker"].to_numpy()[ok]
            notional = (p * df["qty"].to_numpy()[ok]).astype(np.float64)
            starts = np.flatnonzero(np.r_[True, sec[1:] != sec[:-1]])
            ends = np.r_[starts[1:], len(sec)] - 1
            us = sec[starts]
            hi[us] = np.fmax(hi[us], np.maximum.reduceat(p, starts).astype(np.float32))
            lo[us] = np.fmin(lo[us], np.minimum.reduceat(p, starts).astype(np.float32))
            px[us] = p[ends]
            side[us] = np.where(bm[ends], -1, 1)                 # buyer is maker -> taker sold
            signed = np.where(bm, -notional, notional)
            off = int(sec[0])
            bc = np.bincount(sec - off, signed)
            net[off: off + len(bc)] += bc.astype(np.float32)
            del df
    px = pd.Series(px).ffill().to_numpy()
    return {"start_ms": start_ms, "px": px, "hi": hi, "lo": lo, "side": side, "net": net}


def cdf_by_day(z: np.ndarray, n_days: int) -> np.ndarray:
    """cdf[d, b]: share of |z| <= EDGES[b+1] over the previous LOOKBACK_D days (NaN early)."""
    az = np.abs(z[: n_days * E.DAY_S]).reshape(n_days, E.DAY_S)
    hist = np.zeros((n_days, len(E.EDGES) - 1))
    for d in range(n_days):
        v = az[d][np.isfinite(az[d])]
        hist[d] = np.histogram(np.clip(v, 0, E.EDGES[-1] * 0.999), bins=E.EDGES)[0]
    out = np.full(hist.shape, np.nan)
    for d in range(E.LOOKBACK_D, n_days):
        h = hist[d - E.LOOKBACK_D: d].sum(axis=0)
        if h.sum() >= 0.5 * E.LOOKBACK_D * E.DAY_S:
            out[d] = np.cumsum(h) / h.sum()
    return out


@njit(cache=True)
def first_passage(idx, pos, px, hi, lo, delta, hmax):
    """Value (bp) of a fill at px[i] with position pos (+1 long, -1 short): +delta on reversion,
    -delta on adverse (adverse wins a tie within one second), else mark to market at i + hmax."""
    out = np.full(len(idx), np.nan)
    n = len(px)
    for k in range(len(idx)):
        i = idx[k]
        if i + hmax >= n:
            continue
        p = float(px[i])
        sgn = 1.0 if pos[k] > 0 else -1.0
        up = p * (1.0 + delta * 1e-4)
        dn = p * (1.0 - delta * 1e-4)
        v = 0.0
        done = False
        for j in range(i + 1, i + hmax + 1):
            h = float(hi[j])
            l = float(lo[j])
            if h != h:                      # no trade in this second
                continue
            adverse = h >= up if sgn < 0 else l <= dn
            revert = l <= dn if sgn < 0 else h >= up
            if adverse:
                v = -delta
                done = True
                break
            if revert:
                v = delta
                done = True
                break
        if not done:
            v = sgn * np.log(float(px[i + hmax]) / p) * 1e4
        out[k] = v
    return out


def samples(az: dict, side: np.ndarray, net60: np.ndarray, cdf: np.ndarray) -> pd.DataFrame:
    n = az["n_days"] * E.DAY_S
    i = np.arange(2 * E.LOOKBACK_D * E.DAY_S, n, STEP_S)
    i = i[(i % az["Rs"]) >= MIN_TAU]
    y = az["y"][i]
    z = az["z"][i]
    sy = np.sign(y).astype(np.int8)
    keep = np.isfinite(z) & (sy != 0) & (side[i] == sy)
    i, y, z, sy = i[keep], y[keep], z[keep], sy[keep]
    b = np.clip(np.searchsorted(E.EDGES, np.abs(z), side="left") - 1, 0, len(E.EDGES) - 2)
    u = cdf[i // E.DAY_S, b]
    return pd.DataFrame({"i": i, "pos": -sy, "u": u, "absy_bp": np.abs(y) * 1e4,
                         "flow_away": np.sign(net60[i]) == sy})


CHUNKS = [MONTHS[i:i + 3] for i in range(1, len(MONTHS), 3)]   # each with the previous month as warm-up


def build(sym: str) -> None:
    """Chunked by 3 target months plus 1 warm-up month, to bound memory. Baselines need 28 days
    of history (14 for the scale, 14 for the quantiles), which the warm-up month covers, so every
    sample sees the same history as in a single pass. Lost: the first chunk's warm-up month and
    the last 15 minutes of each chunk (no complete first-passage window)."""
    tick = ticks()[sym]
    for R in RS_MIN:
        p = RES / f"rev_{sym}_R{R}.parquet"
        if p.exists():
            continue
        parts = []
        for target in CHUNKS:
            warm = MONTHS[MONTHS.index(target[0]) - 1]
            months = [warm] + target
            g = grid_hl(sym, months)
            day0 = int((pd.Timestamp(months[0] + "-01", tz="UTC")
                        - pd.Timestamp(MONTHS[0] + "-01", tz="UTC")).days)
            warm_s = int((pd.Timestamp(target[0] + "-01", tz="UTC")
                          - pd.Timestamp(warm + "-01", tz="UTC")).total_seconds())
            cs = np.cumsum(g.pop("net").astype(np.float64))
            net60 = np.r_[np.full(60, np.nan), cs[60:] - cs[:-60]].astype(np.float32)
            del cs
            az = anchored_z(g["px"], R)
            cdf = cdf_by_day(az["z"], az["n_days"])
            sm = samples(az, g["side"], net60, cdf)
            del az, cdf, net60
            gc.collect()
            sm = sm[sm["i"] >= warm_s].reset_index(drop=True)
            idx = sm["i"].to_numpy()
            for d in DELTAS_BP:
                sm[f"v{d}"] = first_passage(idx, sm["pos"].to_numpy(), g["px"], g["hi"], g["lo"],
                                            float(d), HMAX_S)
            sm["day"] = idx // E.DAY_S + day0
            sm["tick_bp"] = tick / g["px"][idx] * 1e4
            sm["i"] = idx + day0 * E.DAY_S
            parts.append(sm)
            del g
            gc.collect()
            log.info("%s R=%d %s..%s: %d samples", sym, R, target[0], target[-1], len(sm))
        pd.concat(parts, ignore_index=True).to_parquet(p)


def summary(group: str) -> pd.DataFrame:
    rows = []
    for R in RS_MIN:
        for d in DELTAS_BP:
            col = f"v{d}"
            cols = ["u", "day", "flow_away", "tick_bp", "absy_bp", col]
            df = pd.concat([pd.read_parquet(RES / f"rev_{s}_R{R}.parquet", columns=cols)
                            .astype({"u": "float32", "tick_bp": "float32", "absy_bp": "float32",
                                     col: "float32"}).assign(sym=s)
                            for s in GROUPS[group]], ignore_index=True)
            df["bin"] = pd.cut(df["u"], U_BINS, right=False)
            x = df[df[col].notna() & (df["tick_bp"] * 2 <= d)]        # δ >= 2 ticks
            for b, xb in x.groupby("bin", observed=True):
                for split, xs in (("all", xb), ("flow_away", xb[xb.flow_away]),
                                  ("flow_back", xb[~xb.flow_away])):
                    dv = xs.groupby("day")[col].agg(["sum", "count"]).rename(columns={"count": "n"})
                    lo, hi = block_ci(dv) if split == "all" else (np.nan, np.nan)
                    rows.append({"R_min": R, "delta_bp": d, "u_bin": str(b), "split": split,
                                 "n": len(xs), "syms": xs["sym"].nunique(),
                                 "band_bp": xs["absy_bp"].median(),
                                 "p_rev": (xs[col] >= d - 1e-9).mean(), "p_adv": (xs[col] <= -d + 1e-9).mean(),
                                 "value_bp": xs[col].mean(), "ci_lo": lo, "ci_hi": hi,
                                 "value_net2_bp": xs[col].mean() - 2.0})
    out = pd.DataFrame(rows)
    out.to_csv(RES / f"summary_rev_{group}.csv", index=False)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "summary"])
    ap.add_argument("--group", required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    if a.cmd == "build":
        for s in GROUPS[a.group]:
            build(s)
    else:
        df = summary(a.group)
        pd.set_option("display.width", 250)
        print(df[df.split == "all"].sort_values("value_bp", ascending=False).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
