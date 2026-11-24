"""Stage A-anchored: breaks of a band fixed to an anchor (see DESIGN.md).

    python -m mm_tick.anchored events  --group discovery
    python -m mm_tick.anchored summary --group discovery
"""
from __future__ import annotations

import argparse
import gc
import logging

import numpy as np
import pandas as pd
from numba import njit

from . import events as E
from .run import GROUPS, MONTHS, PRIMARY_D, RES, block_ci, ticks

RS_MIN = (5, 15)
HORIZONS_S = (30, 60, 300, 900)
BUCKET_S = 10
MIN_TAU = 10
log = logging.getLogger("mm_tick.anchored")


def anchored_z(px: np.ndarray, R_min: int) -> dict:
    """z = y / s for windows of R minutes; y = log(p / anchor). Uses only data before t."""
    Rs = R_min * 60
    n_days = len(px) // E.DAY_S
    n = n_days * E.DAY_S
    lp = np.log(px[:n])
    # anchor: last price at the start of the window = price at the end of the previous second
    w = lp.reshape(-1, Rs)
    anchor = np.r_[lp[0], w[:-1, -1]]
    y = (w - anchor[:, None]).astype(np.float32).reshape(-1)
    del w, anchor
    cs = np.cumsum(np.nan_to_num(np.abs(np.diff(lp, prepend=lp[0]))))
    del lp
    rv = np.full(n, np.nan, dtype=np.float32)
    rv[900:] = cs[900:] - cs[:-900]
    del cs
    n_b = Rs // BUCKET_S
    w_per_h = 3600 // Rs
    ay = np.abs(y).reshape(n_days, 24, w_per_h, n_b, BUCKET_S)
    base_y = np.nanmean(ay, axis=(2, 4))                                  # [day, hour, bucket]
    del ay
    base_y = (pd.DataFrame(base_y.reshape(n_days, -1)).rolling(E.LOOKBACK_D, min_periods=E.LOOKBACK_D)
              .mean().shift(1).to_numpy().reshape(n_days, 24, n_b))
    base_rv = E._prior_day_mean(E._per_day_hour(rv, n_days))            # [day, hour]
    s = (base_y / base_rv[:, :, None]).astype(np.float32)                # [day, hour, bucket]
    rv5 = rv.reshape(n_days, 24, w_per_h, n_b, BUCKET_S)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = y.reshape(n_days, 24, w_per_h, n_b, BUCKET_S) / (s[:, :, None, :, None] * rv5)
    del rv, rv5
    return {"y": y, "z": z.reshape(-1), "n_days": n_days, "Rs": Rs}


@njit(cache=True)
def _first_breaks(z, k_sec, Rs, min_tau):
    out = []
    i = 0
    n = len(z)
    while i < n:
        w_end = (i // Rs + 1) * Rs
        j = i + min_tau
        while j < w_end and j < n:
            zj, kj = z[j], k_sec[j]
            if np.isfinite(zj) and np.isfinite(kj) and abs(zj) > kj:
                out.append(j)
                break
            j += 1
        i = w_end
    return np.array(out, dtype=np.int64)


def anchored_breaks(az: dict, k: np.ndarray, j: int) -> pd.DataFrame:
    n = az["n_days"] * E.DAY_S
    k_sec = np.repeat(k[:, j], E.DAY_S)[:n]
    idx = _first_breaks(az["z"][:n], k_sec, az["Rs"], MIN_TAU)
    return pd.DataFrame({"i": idx, "sign": np.sign(az["y"][idx]).astype(int),
                         "absz": np.abs(az["z"][idx]), "k": k_sec[idx]})


def matched_controls(n_days: int, ev: pd.DataFrame, Rs: int, rng) -> pd.DataFrame:
    """Random day and window within the same UTC hour, same τ, random direction."""
    i = ev["i"].to_numpy()
    hour = (i % E.DAY_S) // 3600
    tau = i % Rs
    day = rng.integers(2 * E.LOOKBACK_D, n_days, len(i))
    win = rng.integers(0, 3600 // Rs, len(i))
    ii = day * E.DAY_S + hour * 3600 + win * Rs + tau
    return pd.DataFrame({"i": ii, "sign": rng.choice([-1, 1], len(i)), "absz": np.nan, "k": np.nan})


def build(sym: str, seed: int = 0) -> None:
    tick = ticks()[sym]
    g = E.second_grid(sym, MONTHS)
    px = g["px"]
    for k_ in ("buy", "sell", "cnt"):
        g.pop(k_)
    gc.collect()
    rng = np.random.default_rng(seed)
    for R in RS_MIN:
        todo = [q for q in E.QS if not (RES / f"anch_{sym}_R{R}_q{q}.parquet").exists()]
        if not todo:
            continue
        az = anchored_z(px, R)
        k = E.thresholds(az["z"], az["n_days"])
        pending = []
        for j, q in enumerate(E.QS):
            if q not in todo:
                continue
            ev = anchored_breaks(az, k, j)
            ev = ev[ev["i"] >= 2 * E.LOOKBACK_D * E.DAY_S].reset_index(drop=True)
            ctl = matched_controls(az["n_days"], ev, az["Rs"], rng)
            both = pd.concat([ev.assign(ctl=False), ctl.assign(ctl=True)], ignore_index=True)
            both = both.sort_values("i", kind="stable").reset_index(drop=True)
            both["absy_bp"] = np.abs(az["y"][both["i"].to_numpy()]) * 1e4
            pending.append((q, both))
        del az, k
        gc.collect()
        for q, both in pending:                     # price lookups after the big arrays are freed
            out = E.outcomes(sym, MONTHS, g["start_ms"], both, horizons=HORIZONS_S)
            out["cost"] = [E.cost_bp(tick, v) for v in px[out["i"].to_numpy()]]
            out["day"] = out["i"] // E.DAY_S
            out.to_parquet(RES / f"anch_{sym}_R{R}_q{q}.parquet")
            log.info("%s R=%d q=%s: %d events", sym, R, q, int((~out["ctl"]).sum()))
        del pending
        gc.collect()


def summary(group: str) -> pd.DataFrame:
    syms = GROUPS[group]
    rows = []
    for R in RS_MIN:
        for q in E.QS:
            for d in E.DELAYS_MS:
                for h in HORIZONS_S:
                    col = f"g_d{d}_h{h}"
                    df = pd.concat([pd.read_parquet(RES / f"anch_{s}_R{R}_q{q}.parquet",
                                                    columns=["ctl", "day", "cost", "absy_bp", col])
                                    for s in syms], ignore_index=True)
                    for ctl in (False, True):
                        x = df[~df[col].isna() & (df["ctl"] == ctl)]
                        net = x[col] - x["cost"]
                        dv = (pd.DataFrame({"day": x["day"], "v": net}).groupby("day")["v"]
                              .agg(["sum", "count"]).rename(columns={"count": "n"}))
                        lo, hi = block_ci(dv) if not ctl else (np.nan, np.nan)
                        rows.append({"R_min": R, "q": q, "d_ms": d, "h_s": h, "control": ctl,
                                     "n": len(x), "band_bp": x["absy_bp"].median() if not ctl else np.nan,
                                     "g_bp": x[col].mean(), "net_bp": net.mean(), "ci_lo": lo, "ci_hi": hi,
                                     "p_cont": (x[col] > 0).mean()})
    out = pd.DataFrame(rows)
    out.to_csv(RES / f"summary_anch_{group}.csv", index=False)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["events", "summary"])
    ap.add_argument("--group", required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    if a.cmd == "events":
        for s in GROUPS[a.group]:
            build(s)
    else:
        df = summary(a.group)
        pd.set_option("display.width", 250)
        prim = df[(df.d_ms == PRIMARY_D) & ~df.control].sort_values("net_bp", ascending=False)
        print(prim.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
