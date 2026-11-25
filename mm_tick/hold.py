"""Stage H: cut a held position or keep it (see DESIGN.md).

    python -m mm_tick.hold build      # checkpoint rows -> results/hold_rows.parquet
    python -m mm_tick.hold fit

One row per (trip, checkpoint) while the trip is open. Target A = final PnL - PnL of a taker
cut now. One Bayesian additive linear model per checkpoint; the policy cuts at the first
checkpoint with predicted A < 0.
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
from .bayes import TEST, TRAIN, TRAIN_TUNE, VALID, Bins, predict
from .epnl import LAMBDAS, day_boot, normal_equations, ridge
from .run import RES, ticks
from .toxic import window_features

OUT = RES / "hold_rows.parquet"
CHECKS = (5, 10, 20, 30, 60, 120, 300, 600, 900, 1200, 1500)      # seconds after entry
FEATURES = (["ret_1s", "ret_5s", "ret_30s", "ret_120s", "ret_600s",
             "ofi_1s", "ofi_5s", "ofi_30s", "ofi_120s", "ofi_600s",
             "cnt_5s", "cnt_30s", "cnt_120s", "path_30s", "path_120s", "path_600s",
             "size_rel", "log_dt_last", "u", "dz", "spread_ticks", "tick_bp", "hour_sin", "hour_cos",
             "unreal_bp", "to_tp_bp", "need", "improved"])
log = logging.getLogger("mm_tick.hold")


def last_price_before(t, price, side, sgn, when):
    """Price of the last trade with aggressor side sgn strictly before each time in `when`."""
    idx = np.flatnonzero(side == sgn)
    if not len(idx):
        return np.full(len(when), np.nan)
    j = np.searchsorted(t[idx], when, side="left") - 1
    return np.where(j >= 0, price[idx[np.maximum(j, 0)]], np.nan)


def cut_price(t, price, side, d, when, tick_px):
    """Estimated touch a taker cut hits at `when`: a long sells at the bid, a short buys at the ask."""
    ls = last_price_before(t, price, side, -1, when)
    lb = last_price_before(t, price, side, 1, when)
    bid = np.fmin(ls, lb - tick_px)
    ask = np.fmax(lb, ls + tick_px)
    return np.where(d > 0, bid, ask)


def rows_for_trips(t, price, side, notional, trips, start_ms, u, anchor, den, need, tick):
    """trips: DataFrame with t (entry ms), ex_t, d, entry (price), tp (price), tick_px, pnl_bp,
    improved. Returns the checkpoint rows."""
    n_tr = len(trips)
    c = np.tile(np.array(CHECKS, np.int64), n_tr)
    k = np.repeat(np.arange(n_tr), len(CHECKS))
    tau = trips["t"].to_numpy()[k] + c * 1000
    alive = trips["ex_t"].to_numpy()[k] > tau
    c, k, tau = c[alive], k[alive], tau[alive]
    tr = trips.iloc[k].reset_index(drop=True)
    d = tr["d"].to_numpy().astype(np.float64)
    entry = tr["entry"].to_numpy()
    tick_px = tr["tick_px"].to_numpy()
    lp = np.log(price)
    f = window_features(t, lp, side, notional, tau, d)
    bid, ask = np.exp(f.pop("_bid")), np.exp(f.pop("_ask"))
    out = pd.DataFrame({"trip": tr["trip"].to_numpy(), "c": c.astype(np.int32), "t": tau, "d": d.astype(np.int8)})
    for name, v in f.items():
        out[name] = v.astype(np.float32)
    mid = 0.5 * (bid + ask)
    out["spread_ticks"] = ((ask - bid) / tick_px).astype(np.float32)
    out["unreal_bp"] = (d * (mid - entry) / entry * 1e4).astype(np.float32)
    out["to_tp_bp"] = (d * (tr["tp"].to_numpy() - mid) / entry * 1e4).astype(np.float32)
    sec = (tau - start_ms) // 1000 - 1
    oks = (sec >= 0) & (sec < len(u))
    sec_c = np.clip(sec, 0, len(u) - 1)
    out["u"] = np.where(oks, u[sec_c], np.nan).astype(np.float32)
    last = np.maximum(np.searchsorted(t, tau, side="left") - 1, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (lp[last] - anchor[sec_c]) / den[sec_c]
    out["dz"] = np.where(oks, d * z, np.nan).astype(np.float32)
    day = (tau - start_ms) // 86_400_000
    out["need"] = need[np.clip(day, 0, len(need) - 1)].astype(np.float32)
    out["tick_bp"] = (tick_px / price[last] * 1e4).astype(np.float32)
    hour = ((tau // 1000) % 86_400) / 3600.0
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24).astype(np.float32)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24).astype(np.float32)
    out["improved"] = tr["improved"].to_numpy().astype(np.float32)
    # outcome of a cut executed one delay later, unless the trip closed on its own first
    ex_at = tau + xs.DELAY_MS
    xp = cut_price(t, price, side, d, ex_at, tick_px)
    cut = d * (xp - entry) / entry * 1e4 - xs.MAKER_BP - xs.TAKER_BP
    final = tr["pnl_bp"].to_numpy().astype(np.float64)
    closes_first = tr["ex_t"].to_numpy() <= ex_at
    cut = np.where(closes_first | ~np.isfinite(cut), final, cut)
    out["cut_bp"] = cut.astype(np.float32)
    out["A"] = (final - cut).astype(np.float32)
    return out


def build_symbol(sym: str):
    tick = ticks()[sym]
    sim = [m for m in xs.SIM_MONTHS if m in xs.available(sym)]
    if not sim:
        return None, None
    need = xs.need_by_day(sym, tick)
    u = xs.u_series(sym, 15)
    anchor, den, _ = G.band_series(sym)
    start_ms = int(xs.START.timestamp() * 1000)
    trip_frames, row_frames = [], []
    n0 = 0
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
        parts = []
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(t)]):
            m = float(mult[a])
            r = xs.simulate_x_full(t[a:b], np.rint(px[a:b] / m), side[a:b], u, need, start_ms,
                                   xs.RULES["hybrid"], 0.8, xs.EXIT_U, False,
                                   xs.DELAY_MS, xs.TIMEOUT_MS, xs.MAKER_BP, xs.TAKER_BP, 0.0)
            et, pl, tp, im, sd, ex, en, tpp = r
            parts.append(pd.DataFrame({"t": et, "ex_t": ex, "pnl_bp": pl.astype(np.float32), "by_tp": tp,
                                       "improved": im, "d": sd, "entry": en * m * tick, "tp": tpp * m * tick,
                                       "tick_px": m * tick}))
        trips = pd.concat(parts, ignore_index=True)
        if not len(trips):
            continue
        trips["trip"] = np.arange(n0, n0 + len(trips))
        n0 += len(trips)
        row_frames.append(rows_for_trips(t, price, side, notional, trips, start_ms, u, anchor, den, need, tick))
        trip_frames.append(trips)
        del t, price, px, notional, side, mult
        gc.collect()
    if not trip_frames:
        return None, None
    trips = pd.concat(trip_frames, ignore_index=True)
    rows = pd.concat(row_frames, ignore_index=True)
    trips["sym"] = sym
    rows["sym"] = sym
    return trips, rows


def build() -> None:
    xs.set_period("main")
    part = RES / "hold_parts"
    part.mkdir(exist_ok=True)
    for s in pd.read_csv(xs.UNIVERSE)["sym"]:
        pt, pr = part / f"{s}_trips.parquet", part / f"{s}_rows.parquet"
        if pt.exists():
            continue
        try:
            trips, rows = build_symbol(s)
        except FileNotFoundError:
            trips = None
        if trips is not None:
            rows.to_parquet(pr)
            trips.to_parquet(pt)
            log.info("%s: %d trips, %d rows", s, len(trips), len(rows))
    start_ms = int(xs.START.timestamp() * 1000)
    first = int((pd.Timestamp(xs.SIM_MONTHS[0] + "-01", tz="UTC") - xs.START).days) + xs.SEL_LOOKBACK_D
    trips = pd.concat([pd.read_parquet(p) for p in sorted(part.glob("*_trips.parquet"))], ignore_index=True)
    trips["day"] = ((trips["t"] - start_ms) // 86_400_000).astype(np.int32)
    trips = trips[trips["day"] >= first].copy()
    trips["month"] = (xs.START + pd.to_timedelta(trips["day"], unit="D")).dt.strftime("%Y-%m")
    trips.to_parquet(RES / "hold_trips.parquet")
    log.info("trips: %d", len(trips))


def _rows(month_sel) -> pd.DataFrame:
    """Checkpoint rows of the trips whose entry month is in month_sel."""
    trips = pd.read_parquet(RES / "hold_trips.parquet", columns=["sym", "trip", "month", "day"])
    trips = trips[trips["month"].isin(month_sel)]
    part = RES / "hold_parts"
    out = []
    for s, g in trips.groupby("sym"):
        r = pd.read_parquet(part / f"{s}_rows.parquet")
        r = r.merge(g[["trip", "month", "day"]], on="trip", how="inner")
        out.append(r)
    return pd.concat(out, ignore_index=True)


def fit_checkpoint(r_tr, r_va):
    """Choose lambda on validation MSE, return (bins, w, b0, lam, mse table)."""
    bins = Bins(r_tr, features=FEATURES)
    c_tr, c_va = bins.codes(r_tr), bins.codes(r_va)
    y_tr, y_va = r_tr["A"].to_numpy().astype(np.float64), r_va["A"].to_numpy().astype(np.float64)
    A, b = normal_equations(c_tr, bins, y_tr)
    best = None
    for lam in LAMBDAS:
        w, b0 = ridge(A, b, lam)
        mse = float(np.mean((y_va - predict(c_va, w, b0, bins)) ** 2))
        if best is None or mse < best[0]:
            best = (mse, lam)
    return best[1]


def policy(rows: pd.DataFrame, trips: pd.DataFrame, pred: np.ndarray) -> pd.DataFrame:
    """Cut at the first checkpoint with pred < 0. Returns trips with the policy PnL and cut time."""
    r = rows[["sym", "trip", "c", "cut_bp"]].copy()
    r["go"] = pred < 0
    first = r[r["go"]].sort_values("c").groupby(["sym", "trip"]).first().reset_index()
    tr = trips.merge(first[["sym", "trip", "c", "cut_bp"]], on=["sym", "trip"], how="left")
    tr["pol_bp"] = np.where(tr["c"].notna(), tr["cut_bp"], tr["pnl_bp"])
    # hindsight ceiling: best of holding and cutting at any open checkpoint
    best_cut = rows.groupby(["sym", "trip"])["cut_bp"].max().rename("best_cut").reset_index()
    tr = tr.merge(best_cut, on=["sym", "trip"], how="left")
    tr["oracle_bp"] = np.fmax(tr["pnl_bp"], tr["best_cut"].fillna(-np.inf))
    return tr


def run_fit() -> None:
    trips = pd.read_parquet(RES / "hold_trips.parquet")
    rows_design = _rows(TRAIN)
    rows_test = _rows(TEST)
    for r in (rows_design, rows_test):
        r["improved"] = r["improved"].astype(np.float32)
    lams, preds = {}, np.full(len(rows_test), np.nan)
    pred_d = np.full(len(rows_design), np.nan)
    for c in CHECKS:
        md = rows_design["c"].to_numpy() == c
        mt = rows_test["c"].to_numpy() == c
        rd = rows_design[md]
        lam = fit_checkpoint(rd[rd["month"].isin(TRAIN_TUNE)], rd[rd["month"].isin(VALID)])
        bins = Bins(rd, features=FEATURES)
        A, b = normal_equations(bins.codes(rd), bins, rd["A"].to_numpy().astype(np.float64))
        w, b0 = ridge(A, b, lam)
        preds[mt] = predict(bins.codes(rows_test[mt]), w, b0, bins)
        pred_d[md] = predict(bins.codes(rd), w, b0, bins)
        lams[c] = lam
        log.info("checkpoint %d s: lambda %g, %d design rows, %d test rows", c, lam, md.sum(), mt.sum())
    rng = np.random.default_rng(0)
    out = RES / "hold_model"
    out.mkdir(exist_ok=True)
    res = []
    for half, r, p, months in (("design (in-sample)", rows_design, pred_d, TRAIN), ("test", rows_test, preds, TEST)):
        tr = policy(r, trips[trips["month"].isin(months)], p)
        day = tr["day"].to_numpy()
        hold = day_boot(tr["pnl_bp"].to_numpy(), day, rng)
        pol = day_boot(tr["pol_bp"].to_numpy(), day, rng)
        diff = day_boot((tr["pol_bp"] - tr["pnl_bp"]).to_numpy(), day, rng)
        orc = tr["oracle_bp"].mean()
        res.append({"half": half, "n_trips": len(tr), "hold": hold[0], "policy": pol[0], "policy_lo": pol[1],
                    "policy_hi": pol[2], "gain": diff[0], "gain_lo": diff[1], "gain_hi": diff[2],
                    "cut_share": tr["c"].notna().mean(), "oracle": orc,
                    "H1": bool(half == "test" and pol[0] > 0 and pol[1] > 0)})
        if half == "test":
            test_tr = tr
    res = pd.DataFrame(res)
    by_month = test_tr.groupby("month").agg(n=("pol_bp", "size"), hold=("pnl_bp", "mean"),
                                            policy=("pol_bp", "mean"), cut=("c", lambda v: v.notna().mean()))
    when = test_tr.groupby(test_tr["c"].fillna(-1)).agg(n=("pol_bp", "size"), policy=("pol_bp", "mean"),
                                                        hold=("pnl_bp", "mean"))
    # per checkpoint: rank IC of the prediction with A, and the mean A where pred < 0
    ic = []
    for c in CHECKS:
        mt = rows_test["c"].to_numpy() == c
        a_ = rows_test.loc[mt, "A"].to_numpy()
        p_ = preds[mt]
        ic.append({"c": c, "n": int(mt.sum()), "lam": lams[c],
                   "ic": float(np.corrcoef(pd.Series(p_).rank(), pd.Series(a_).rank())[0, 1]),
                   "mean_A": float(a_.mean()), "share_pred_neg": float((p_ < 0).mean()),
                   "A_where_pred_neg": float(a_[p_ < 0].mean()) if (p_ < 0).any() else np.nan})
    ic = pd.DataFrame(ic)
    res.to_csv(out / "result.csv", index=False)
    by_month.to_csv(out / "by_month.csv")
    when.to_csv(out / "cut_time.csv")
    ic.to_csv(out / "checkpoints.csv", index=False)
    pd.set_option("display.width", 220)
    for name, x in (("result", res), ("by month", by_month), ("cut time", when), ("checkpoints", ic)):
        print("==", name)
        print(x.round(4).to_string())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "fit"])
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    build() if a.cmd == "build" else run_fit()


if __name__ == "__main__":
    main()
