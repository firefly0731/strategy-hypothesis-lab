"""Stage C: ceiling for a fill-toxicity predictor (see DESIGN.md).

    python -m mm_tick.ceiling trips      # stage X primary trips, trip level, 2026 period
    python -m mm_tick.ceiling analyse
"""
from __future__ import annotations

import argparse
import gc
import logging

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from statistics import NormalDist

from . import events as E
from . import xs
from .run import RES, ticks

OUT = RES / "ceiling_trips.parquet"
AUCS = (0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90)
ICS = (0.05, 0.10, 0.15, 0.20, 0.30)
FRACS = tuple(np.round(np.arange(0.1, 1.01, 0.1), 1))
N_DRAWS = 20
log = logging.getLogger("mm_tick.ceiling")
_ND = NormalDist()
_ppf = np.vectorize(_ND.inv_cdf, otypes=[float])


def auc(score: np.ndarray, y: np.ndarray) -> float:
    """Mann-Whitney AUC of score for the positive class y == 1."""
    r = pd.Series(score).rank().to_numpy()
    n1 = y.sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (len(y) - n1)))


def trips_for(sym: str) -> pd.DataFrame | None:
    """Trip-level PnL of the stage X primary settings (R 15, u_on 0.8, hold, hybrid)."""
    tick = ticks()[sym]
    sim = [m for m in xs.SIM_MONTHS if m in xs.available(sym)]
    if not sim:
        return None
    need = xs.need_by_day(sym, tick)
    u = xs.u_series(sym, 15)
    start_ms = int(xs.START.timestamp() * 1000)
    out = []
    for mo in sim:
        tb = pq.read_table(E.trade_path(sym, mo), columns=["t", "px", "buyer_maker"])
        t = tb.column("t").to_numpy()
        raw = tb.column("px").to_numpy() / tick
        px = np.rint(raw)
        if float(np.mean(np.abs(raw - px) > 1e-6)) > 0.01:
            continue
        del raw
        side = np.where(tb.column("buyer_maker").to_numpy(), -1, 1).astype(np.int8)
        del tb
        mult = xs.effective_mult(t, px.astype(np.int64))
        cuts = np.flatnonzero(np.diff(mult)) + 1
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(t)]):
            m = float(mult[a])
            et, pl, tp, im = xs.simulate_x(t[a:b], np.rint(px[a:b] / m), side[a:b], u, need, start_ms,
                                           xs.RULES["hybrid"], 0.8, xs.EXIT_U, False,
                                           xs.DELAY_MS, xs.TIMEOUT_MS, xs.MAKER_BP, xs.TAKER_BP)
            out.append(pd.DataFrame({"t": et, "pnl_bp": pl.astype(np.float32), "by_tp": tp}))
        del t, px, side, mult
        gc.collect()
    if not out:
        return None
    df = pd.concat(out, ignore_index=True)
    df["sym"] = sym
    return df


def build_trips() -> None:
    xs.set_period("main")
    frames = []
    for s in pd.read_csv(xs.UNIVERSE)["sym"]:
        try:
            d = trips_for(s)
        except FileNotFoundError:
            d = None
        if d is not None:
            frames.append(d)
            log.info("%s: %d trips", s, len(d))
    df = pd.concat(frames, ignore_index=True)
    start_ms = int(xs.START.timestamp() * 1000)
    df["day"] = ((df["t"] - start_ms) // 86_400_000).astype(np.int32)
    first = int((pd.Timestamp(xs.SIM_MONTHS[0] + "-01", tz="UTC") - xs.START).days) + xs.SEL_LOOKBACK_D
    cut = int((pd.Timestamp(xs.DESIGN_END + "-01", tz="UTC") - xs.START).days)
    df = df[df["day"] >= first]
    df["half"] = np.where(df["day"] < cut, "design", "confirm")
    df.to_parquet(OUT)


def keep_rule(goodness: np.ndarray, pnl: np.ndarray, design: np.ndarray):
    """Choose the kept fraction on the design half; return (frac, threshold)."""
    g_d, p_d = goodness[design], pnl[design]
    best = (-np.inf, 1.0, -np.inf)
    for f in FRACS:
        thr = np.quantile(g_d, 1 - f) if f < 1 else -np.inf
        v = p_d[g_d >= thr].mean()
        if v > best[0]:
            best = (v, f, thr)
    return best[1], best[2]


def analyse(seed: int = 0) -> pd.DataFrame:
    df = pd.read_parquet(OUT, columns=["pnl_bp", "half"])
    pnl = df["pnl_bp"].to_numpy().astype(np.float64)
    design = (df["half"] == "design").to_numpy()
    conf = ~design
    y = (pnl < 0).astype(np.float64)
    rng = np.random.default_rng(seed)
    z_rank = _ppf((pd.Series(pnl).rank(method="average").to_numpy() - 0.5) / len(pnl))
    rows = []
    specs = [("auc", a) for a in AUCS] + [("ic", c) for c in ICS]
    for kind, q in specs:
        for d in range(N_DRAWS):
            noise = rng.standard_normal(len(pnl))
            if kind == "auc":
                goodness = -(y * np.sqrt(2) * _ND.inv_cdf(q) + noise)
            else:
                goodness = q * z_rank + np.sqrt(1 - q * q) * noise
            f, thr = keep_rule(goodness, pnl, design)
            k_c = conf & (goodness >= thr)
            rows.append({"kind": kind, "quality": q, "draw": d, "frac_design": f,
                         "kept_confirm": k_c.sum() / conf.sum(), "pnl_confirm": pnl[k_c].mean(),
                         "pnl_design": pnl[design & (goodness >= thr)].mean()})
    r = pd.DataFrame(rows)
    out = (r.groupby(["kind", "quality"])
           .agg(frac=("frac_design", "median"), kept_confirm=("kept_confirm", "mean"),
                pnl_design=("pnl_design", "mean"), pnl_confirm=("pnl_confirm", "mean"),
                pnl_confirm_p05=("pnl_confirm", lambda v: np.percentile(v, 5)))
           .reset_index())
    base = {"loss_share": y.mean(), "mean_all": pnl.mean(), "mean_win": pnl[pnl >= 0].mean(),
            "mean_loss": pnl[pnl < 0].mean(), "n": len(pnl)}
    out.to_csv(RES / "summary_ceiling.csv", index=False)
    print(base)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["trips", "analyse"])
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    if a.cmd == "trips":
        build_trips()
    else:
        pd.set_option("display.width", 250)
        print(analyse().round(3).to_string(index=False))


if __name__ == "__main__":
    main()
