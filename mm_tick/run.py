"""Stage A runner: build event tables per symbol, then summarise per group (see DESIGN.md).

    python -m mm_tick.run events  --symbols BTCUSDT ETHUSDT SOLUSDT
    python -m mm_tick.run summary --group discovery
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from . import events as E

RES = Path("C:/Users/smile-user/md_local/results")
MONTHS = E.months_between("2025-11", "2026-10")
GROUPS = {"discovery": E.DISCOVERY, "holdout": E.HOLDOUT, "large_tick": E.LARGE_TICK}
PRIMARY_D = 250
log = logging.getLogger("mm_tick")


def ticks() -> dict:
    p = RES / "ticks.json"
    if p.exists():
        return json.loads(p.read_text())
    ei = json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/exchangeInfo"))
    out = {s["symbol"]: float(next(f for f in s["filters"] if f["filterType"] == "PRICE_FILTER")["tickSize"])
           for s in ei["symbols"]}
    RES.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


def build_events(sym: str, seed: int = 0) -> None:
    tick = ticks()[sym]
    g = E.second_grid(sym, MONTHS)
    for k_ in ("buy", "sell", "cnt"):      # not needed for stage A1/A2 tables
        g.pop(k_)
    gc.collect()
    rng = np.random.default_rng(seed)
    for L in E.LS:
        zs = E.zscores(g, L)
        k = E.thresholds(zs["z"], zs["n_days"])
        for j, q in enumerate(E.QS):
            p = RES / f"ev_{sym}_L{L}_q{q}.parquet"
            if p.exists():
                continue
            ev = E.breaks(zs, k, j, L)
            ev = ev[ev["i"] >= 2 * E.LOOKBACK_D * E.DAY_S].reset_index(drop=True)
            ctl = E.random_controls(zs["n_days"], ev, rng)
            both = pd.concat([ev.assign(ctl=False), ctl.assign(ctl=True)], ignore_index=True)
            both = both.sort_values("i", kind="stable").reset_index(drop=True)
            out = E.outcomes(sym, MONTHS, g["start_ms"], both)
            px = g["px"][out["i"].to_numpy()]
            out["cost"] = [E.cost_bp(tick, v) for v in px]
            out["day"] = out["i"] // E.DAY_S
            out.to_parquet(p)
            log.info("%s L=%d q=%s: %d events", sym, L, q, int((~out["ctl"]).sum()))
        del zs, k
        gc.collect()
    del g
    gc.collect()


def block_ci(day_vals: pd.Series, block=5, n=2000, seed=0):
    """Moving-block bootstrap over days of the mean of per-event values (day sums / counts)."""
    rng = np.random.default_rng(seed)
    s, c = day_vals["sum"].to_numpy(), day_vals["n"].to_numpy()
    m = len(s)
    if m < block * 2:
        return np.nan, np.nan
    starts = rng.integers(0, m - block + 1, (n, int(np.ceil(m / block))))
    idx = (starts[..., None] + np.arange(block)).reshape(n, -1)[:, :m]
    est = s[idx].sum(1) / np.maximum(c[idx].sum(1), 1)
    return np.percentile(est, 2.5), np.percentile(est, 97.5)


def summary(group: str) -> pd.DataFrame:
    syms = GROUPS[group]
    rows = []
    for L in E.LS:
        for q in E.QS:
            frames = [pd.read_parquet(RES / f"ev_{s}_L{L}_q{q}.parquet").assign(sym=s) for s in syms]
            df = pd.concat(frames, ignore_index=True)
            for d in E.DELAYS_MS:
                for h in E.HORIZONS_S:
                    col = f"g_d{d}_h{h}"
                    for ctl in (False, True):
                        x = df[~df[col].isna() & (df["ctl"] == ctl)]
                        net = x[col] - x["cost"]
                        # pool symbols day by day for the block bootstrap
                        dv = pd.DataFrame({"day": x["day"], "v": net}).groupby("day")["v"].agg(["sum", "count"])
                        dv = dv.rename(columns={"count": "n"})
                        lo, hi = block_ci(dv) if not ctl else (np.nan, np.nan)
                        rows.append({"L": L, "q": q, "d_ms": d, "h_s": h, "control": ctl,
                                     "n": len(x), "g_bp": x[col].mean(), "net_bp": net.mean(),
                                     "ci_lo": lo, "ci_hi": hi,
                                     "p_cont": (x[col] > 0).mean(), "p_beats_cost": (net > 0).mean()})
    out = pd.DataFrame(rows)
    out.to_csv(RES / f"summary_{group}.csv", index=False)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["events", "summary"])
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--group")
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    RES.mkdir(parents=True, exist_ok=True)
    if a.cmd == "events":
        for s in a.symbols or GROUPS[a.group]:
            build_events(s)
    else:
        df = summary(a.group)
        pd.set_option("display.width", 250)
        prim = df[(df.d_ms == PRIMARY_D) & ~df.control].sort_values("net_bp", ascending=False)
        print(prim.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
