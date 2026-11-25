"""Stage M: range maker with a profit-target spread, 1-second cancel and exit models (DESIGN.md).

    python -m mm_tick.mspread build                 # pass 1: M0 trips + training rows -> results/mspread/
    python -m mm_tick.mspread fit                   # models A (05..06), B (05..07), C (05..10)
    python -m mm_tick.mspread policy                # pass 2: every (c, theta), 2026-07 (A) and 08..10 (B)
    python -m mm_tick.mspread report                # choice on 2026-07, test 2026-08..10
    python -m mm_tick.mspread policy --period early # the chosen (c, theta) with models C on 2025
    python -m mm_tick.mspread report --period early
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import pickle

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from numba import njit

from . import events as E
from . import grid as G
from . import xs
from .bayes import TAUS, Bins, fit_map, predict
from .depth import boot99
from .epnl import LAMBDAS, MIN_KEPT, normal_equations, ridge
from .run import RES, ticks
from .toxic import window_features

TARGET_BP = 20.0
U_ON = 0.8
SIGNED = ["ret_1s", "ret_5s", "ret_30s", "ret_120s", "ret_600s",
          "ofi_1s", "ofi_5s", "ofi_30s", "ofi_120s", "ofi_600s", "dz"]
MARKET = SIGNED[:10] + ["cnt_5s", "cnt_30s", "cnt_120s", "path_30s", "path_120s", "path_600s",
                        "size_rel", "log_dt_last", "u", "dz", "need", "spread_ticks", "tick_bp",
                        "hour_sin", "hour_cos"]
POSITION = ["unreal_bp", "to_tp_bp", "elapsed_s"]
CHECKS = (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200)
CS = (None, 0.0, 5.0, 10.0, 20.0)
THETAS = (None, 0.3, 0.5, 0.7)
MAX_EXIT_ROWS = 3_000_000
OUT = RES / "mspread"
log = logging.getLogger("mm_tick.mspread")


@njit(cache=True)
def simulate_m(t, px, side, u, need_bp_day, start_ms, month_ms, delay, timeout, maker_bp, taker_bp, target_bp,
               u_on, pred_bid, pred_ask, c, c_on, eta_l, eta_s, b0, e_u, w_u, e_t, w_t, e_e, w_e, theta, x_on):
    """One unit of inventory. Flat: quote mid -/+ h with 2h = need + target (ticks, away from the
    mid, never inside the touch), a side only while its predicted fill PnL >= c (if c_on).
    Fills need a trade through the price. Long: take-profit = max(the ask quote, entry + need +
    target); while held, each second, P(loss) = sigmoid(eta_market + b0 + position terms); if
    > theta (x_on) the take-profit moves once to break-even. 30-min taker timeout.
    Model arrays are per second of the month (index (t - month_ms) // 1000)."""
    n = len(t)
    cap = n // 2 + 1
    ent_t = np.empty(cap, dtype=np.int64)
    ex_t = np.empty(cap, dtype=np.int64)
    pnl = np.empty(cap)
    by_tp = np.empty(cap, dtype=np.bool_)
    sd = np.empty(cap, dtype=np.int8)
    en = np.empty(cap)
    tp0_e = np.empty(cap)
    dfd = np.empty(cap, dtype=np.bool_)
    k = 0
    bid_m = np.nan
    ask_m = np.nan
    q_bid = np.nan
    q_ask = np.nan
    p_bid = np.nan
    p_ask = np.nan
    p_time = -1
    pos = 0
    entry = 0.0
    entry_t = 0
    tp = np.nan
    tp0 = np.nan
    tp_imp = False
    tp_time = 0
    defended = False
    last_chk = -1
    n_u = len(u)
    n_need = len(need_bp_day)
    n_s = len(pred_bid)
    for i in range(n):
        ti = t[i]
        p = px[i]
        s = side[i]
        sec = (ti - start_ms) // 1000 - 1
        ui = u[sec] if 0 <= sec < n_u else np.nan
        dd = (ti - start_ms) // 86_400_000
        need = need_bp_day[dd] if 0 <= dd < n_need else np.nan
        ls = (ti - month_ms) // 1000
        ok_s = 0 <= ls < n_s
        if p_time >= 0 and ti >= p_time:
            q_bid = p_bid
            q_ask = p_ask
            p_time = -1
        if pos == 0:
            if s < 0 and q_bid == q_bid and p < q_bid:
                pos = 1
                entry = q_bid
            elif s > 0 and q_ask == q_ask and p > q_ask:
                pos = -1
                entry = q_ask
            if pos != 0:
                entry_t = ti
                nt = max(np.ceil((need + target_bp) * 1e-4 * entry), 1.0)
                if pos > 0:
                    tp = entry + nt
                    if q_ask == q_ask and q_ask > tp:
                        tp = q_ask
                    tp_imp = ask_m == ask_m and tp < ask_m
                else:
                    tp = entry - nt
                    if q_bid == q_bid and q_bid < tp:
                        tp = q_bid
                    tp_imp = bid_m == bid_m and tp > bid_m
                tp0 = tp
                tp_time = ti + delay
                defended = False
                last_chk = -1
                q_bid = np.nan
                q_ask = np.nan
                p_time = -1
        else:
            closed = False
            if ti >= tp_time:
                if pos > 0 and s > 0 and (p >= tp if tp_imp else p > tp):
                    pnl[k] = (tp - entry) / entry * 1e4 - 2.0 * maker_bp
                    closed = True
                    by_tp[k] = True
                elif pos < 0 and s < 0 and (p <= tp if tp_imp else p < tp):
                    pnl[k] = (entry - tp) / entry * 1e4 - 2.0 * maker_bp
                    closed = True
                    by_tp[k] = True
            if not closed and ti - entry_t >= timeout:
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
                ex_t[k] = ti
                sd[k] = pos
                en[k] = entry
                tp0_e[k] = tp0
                dfd[k] = defended
                k += 1
                pos = 0
            elif x_on and not defended and ok_s and ls != last_chk and ti - entry_t >= 1000 \
                    and bid_m == bid_m and ask_m == ask_m:
                last_chk = ls
                em = eta_l[ls] if pos > 0 else eta_s[ls]
                if em == em:
                    mid = 0.5 * (bid_m + ask_m)
                    un = pos * (mid - entry) / entry * 1e4
                    tt = pos * (tp - mid) / entry * 1e4
                    el = (ti - entry_t) / 1000.0
                    eta = em + b0 + w_u[np.searchsorted(e_u, un, side="right")] \
                        + w_t[np.searchsorted(e_t, tt, side="right")] + w_e[np.searchsorted(e_e, el, side="right")]
                    if 1.0 / (1.0 + np.exp(-eta)) > theta:
                        defended = True
                        if pos > 0:
                            be = np.ceil(entry * (1.0 + 2.0 * maker_bp * 1e-4))
                            if be < tp:
                                tp = be
                                tp_imp = tp < ask_m
                                tp_time = ti + delay
                        else:
                            be = np.floor(entry * (1.0 - 2.0 * maker_bp * 1e-4))
                            if be > tp:
                                tp = be
                                tp_imp = tp > bid_m
                                tp_time = ti + delay
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
            if ui == ui and ui < u_on and need == need and bid_m == bid_m and ask_m == ask_m:
                mid = 0.5 * (bid_m + ask_m)
                hk = max(np.ceil(0.5 * (need + target_bp) * 1e-4 * mid), 1.0)
                d_bid = min(bid_m, np.floor(mid - hk))
                d_ask = max(ask_m, np.ceil(mid + hk))
                if c_on and ok_s:
                    if pred_bid[ls] == pred_bid[ls] and pred_bid[ls] < c:
                        d_bid = np.nan
                    if pred_ask[ls] == pred_ask[ls] and pred_ask[ls] < c:
                        d_ask = np.nan
            same = ((d_bid == q_bid) or (d_bid != d_bid and q_bid != q_bid)) and \
                   ((d_ask == q_ask) or (d_ask != d_ask and q_ask != q_ask))
            if not same:
                if p_time < 0:
                    p_time = ti + delay
                p_bid = d_bid
                p_ask = d_ask
    if pos != 0 and bid_m == bid_m and ask_m == ask_m:
        if pos > 0:
            pnl[k] = (bid_m - entry) / entry * 1e4 - maker_bp - taker_bp
        else:
            pnl[k] = (entry - ask_m) / entry * 1e4 - maker_bp - taker_bp
        by_tp[k] = False
        ent_t[k] = entry_t
        ex_t[k] = t[n - 1]
        sd[k] = pos
        en[k] = entry
        tp0_e[k] = tp0
        dfd[k] = defended
        k += 1
    return ent_t[:k], ex_t[:k], pnl[:k], by_tp[:k], sd[:k], en[:k], tp0_e[:k], dfd[:k]


class Coin:
    """Per-coin period series (band, need, anchor) shared by every month."""

    def __init__(self, sym: str):
        self.sym = sym
        self.tick = ticks()[sym]
        self.need = xs.need_by_day(sym, self.tick)
        self.u = xs.u_series(sym, 15)
        self.anchor, self.den, _ = G.band_series(sym)
        self.start_ms = int(xs.START.timestamp() * 1000)


def month_data(coin: Coin, mo: str):
    tb = pq.read_table(E.trade_path(coin.sym, mo), columns=["t", "px", "qty", "buyer_maker"])
    t = tb.column("t").to_numpy()
    price = tb.column("px").to_numpy()
    raw = price / coin.tick
    px = np.rint(raw)
    if float(np.mean(np.abs(raw - px) > 1e-6)) > 0.01:
        return None
    notional = price * tb.column("qty").to_numpy()
    side = np.where(tb.column("buyer_maker").to_numpy(), -1, 1).astype(np.int8)
    mult = xs.effective_mult(t, px.astype(np.int64))
    return t, price, px, notional, side, mult


def second_features(coin: Coin, mo: str, t, price, side, notional, mult) -> pd.DataFrame:
    """Market features at the start of every second of the month, signed for a long (d = +1)."""
    m0 = int(pd.Timestamp(mo + "-01", tz="UTC").timestamp() * 1000)
    m1 = int((pd.Timestamp(mo + "-01", tz="UTC") + pd.offsets.MonthBegin(1)).timestamp() * 1000)
    tau = np.arange(m0, m1, 1000, dtype=np.int64)
    lp = np.log(price)
    f = window_features(t, lp, side, notional, tau, np.ones(len(tau)))
    bid, ask = np.exp(f.pop("_bid")), np.exp(f.pop("_ask"))
    last = np.maximum(np.searchsorted(t, tau, side="left") - 1, 0)
    df = pd.DataFrame({k: v.astype(np.float32) for k, v in f.items()})
    df["mid_px"] = (0.5 * (bid + ask)).astype(np.float64)
    tick_eff = coin.tick * mult[last]
    df["spread_ticks"] = ((ask - bid) / tick_eff).astype(np.float32)
    sec = (tau - coin.start_ms) // 1000 - 1
    oks = (sec >= 0) & (sec < len(coin.u))
    sc = np.clip(sec, 0, len(coin.u) - 1)
    df["u"] = np.where(oks, coin.u[sc], np.nan).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (lp[last] - coin.anchor[sc]) / coin.den[sc]
    df["dz"] = np.where(oks, z, np.nan).astype(np.float32)
    day = (tau - coin.start_ms) // 86_400_000
    df["need"] = coin.need[np.clip(day, 0, len(coin.need) - 1)].astype(np.float32)
    df["tick_bp"] = (tick_eff / price[last] * 1e4).astype(np.float32)
    hour = ((tau // 1000) % 86_400) / 3600.0
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24).astype(np.float32)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24).astype(np.float32)
    df.loc[np.searchsorted(t, tau, side="left") == 0, MARKET] = np.nan
    return df, m0


def signed(feat: pd.DataFrame, idx: np.ndarray, d: np.ndarray) -> pd.DataFrame:
    x = feat.iloc[idx].reset_index(drop=True)
    for c in SIGNED:
        x[c] = x[c] * d
    return x


def run_sims(coin, mo, data, feat, m0, model, combos):
    """Simulate each (c, theta) combo on one coin-month; returns a trips DataFrame."""
    t, price, px, notional, side, mult = data
    n_s = len(feat)
    z = np.full(n_s, np.nan)
    pb = pa = el = es = z
    b0 = 0.0
    ew = [np.array([0.0]), np.zeros(2)] * 3
    if model is not None:
        cm, xm = model["cancel"], model["exit"]
        ones = np.ones(n_s)
        pb = cm_predict(cm, feat, ones)
        pa = cm_predict(cm, feat, -ones)
        el = market_eta(xm, feat, ones)
        es = market_eta(xm, feat, -ones)
        b0 = xm["b0"]
        ew = []
        for nm in POSITION:
            j = xm["bins"].features.index(nm)
            e = xm["bins"].edges[j]
            w = xm["w"][xm["bins"].offsets[j]: xm["bins"].offsets[j] + xm["bins"].sizes[j]]
            ew += [np.asarray(e, dtype=np.float64), np.asarray(w, dtype=np.float64)]
    cuts = np.flatnonzero(np.diff(mult)) + 1
    out = []
    for c, th in combos:
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(t)]):
            m = float(mult[a])
            r = simulate_m(t[a:b], np.rint(px[a:b] / m), side[a:b], coin.u, coin.need, coin.start_ms, m0,
                           xs.DELAY_MS, xs.TIMEOUT_MS, xs.MAKER_BP, xs.TAKER_BP, TARGET_BP, U_ON,
                           pb, pa, -1e9 if c is None else c, c is not None, el, es, b0,
                           ew[0], ew[1], ew[2], ew[3], ew[4], ew[5], 2.0 if th is None else th, th is not None)
            if len(r[0]):
                out.append(pd.DataFrame({"t": r[0], "t_exit": r[1], "pnl_bp": r[2].astype(np.float32), "by_tp": r[3],
                                         "d": r[4], "entry_k": r[5], "tp_k": r[6], "defended": r[7], "tick_mult": m,
                                         "c": -1.0 if c is None else c, "theta": -1.0 if th is None else th}))
    return pd.concat(out, ignore_index=True) if out else None


def cm_predict(cm, feat, d):
    x = feat[MARKET].copy()
    for c in SIGNED:
        x[c] = x[c] * d
    return predict(cm["bins"].codes(x), cm["w"], cm["b0"], cm["bins"])


def market_eta(xm, feat, d):
    """Sum of the market-feature weights of the exit model (position terms are added in the loop)."""
    x = feat[MARKET].copy()
    for c in SIGNED:
        x[c] = x[c] * d
    bins = xm["bins"]
    eta = np.zeros(len(x))
    for j, f in enumerate(bins.features):
        if f in POSITION:
            continue
        v = x[f].to_numpy(dtype=np.float64)
        e = bins.edges[j]
        cd = np.searchsorted(e, v, side="right")
        cd[~np.isfinite(v)] = len(e) + 1
        eta += xm["w"][bins.offsets[j] + cd]
    return eta


def training_rows(coin, trips, feat, m0, price_scale):
    """Cancel rows (features at the last second a cancel could act) and exit checkpoint rows."""
    d = trips["d"].to_numpy().astype(np.float64)
    tc = (trips["t"].to_numpy() - xs.DELAY_MS - m0) // 1000
    ok = (tc >= 0) & (tc < len(feat))
    can = signed(feat, tc[ok], d[ok])[MARKET]
    can["pnl_bp"] = trips["pnl_bp"].to_numpy()[ok]
    can["t"] = trips["t"].to_numpy()[ok]
    rows = []
    entry_px = trips["entry_k"].to_numpy() * trips["tick_mult"].to_numpy() * price_scale
    tp_px = trips["tp_k"].to_numpy() * trips["tick_mult"].to_numpy() * price_scale
    for k in CHECKS:
        at = trips["t"].to_numpy() + k * 1000
        live = at < trips["t_exit"].to_numpy()
        si = (at - m0) // 1000
        live &= (si >= 0) & (si < len(feat))
        if not live.any():
            continue
        x = signed(feat, si[live], d[live])
        mid = x["mid_px"].to_numpy()
        x = x[MARKET]
        x["unreal_bp"] = (d[live] * (mid - entry_px[live]) / entry_px[live] * 1e4).astype(np.float32)
        x["to_tp_bp"] = (d[live] * (tp_px[live] - mid) / entry_px[live] * 1e4).astype(np.float32)
        x["elapsed_s"] = np.float32(k)
        x["y"] = (trips["pnl_bp"].to_numpy()[live] < 0).astype(np.int8)
        x["t"] = trips["t"].to_numpy()[live]
        rows.append(x)
    ex = pd.concat(rows, ignore_index=True) if rows else None
    return can, ex


def build() -> None:
    xs.set_period("main")
    part = OUT / "parts"
    part.mkdir(parents=True, exist_ok=True)
    for sym in pd.read_csv(xs.UNIVERSE)["sym"]:
        p = part / f"{sym}_trips.parquet"
        if p.exists():
            continue
        try:
            coin = Coin(sym)
        except FileNotFoundError:
            continue
        T, C, X = [], [], []
        for mo in [m for m in xs.SIM_MONTHS if m in xs.available(sym)]:
            data = month_data(coin, mo)
            if data is None:
                continue
            t, price, px, notional, side, mult = data
            feat, m0 = second_features(coin, mo, t, price, side, notional, mult)
            tr = run_sims(coin, mo, data, feat, m0, None, [(None, None)])
            if tr is not None:
                can, ex = training_rows(coin, tr, feat, m0, coin.tick)
                T.append(tr)
                C.append(can)
                if ex is not None:
                    X.append(ex)
            del data, feat, t, price, px, notional, side, mult
            gc.collect()
        if T:
            for nm, fr in (("cancel", C), ("exit", X), ("trips", T)):      # trips last: marks the coin done
                df = pd.concat(fr, ignore_index=True)
                df["sym"] = sym
                df.to_parquet(part / f"{sym}_{nm}.parquet")
            log.info("%s: %d trips", sym, sum(len(x) for x in T))


def _month(t_ms: np.ndarray, period="main") -> np.ndarray:
    return pd.to_datetime(t_ms, unit="ms", utc=True).strftime("%Y-%m").to_numpy()


def fit() -> None:
    part = OUT / "parts"
    can = pd.concat([pd.read_parquet(p) for p in sorted(part.glob("*_cancel.parquet"))], ignore_index=True)
    ex = pd.concat([pd.read_parquet(p) for p in sorted(part.glob("*_exit.parquet"))], ignore_index=True)
    can["month"], ex["month"] = _month(can["t"].to_numpy()), _month(ex["t"].to_numpy())
    if len(ex) > MAX_EXIT_ROWS * 2:
        ex = ex.sample(MAX_EXIT_ROWS * 2, random_state=0)
    log.info("cancel rows %d, exit rows %d", len(can), len(ex))
    # tuning: fit 05..06, choose on 07
    y = can["pnl_bp"].to_numpy().astype(np.float64)
    m = can["month"].to_numpy()
    tr, va = np.isin(m, ("2026-05", "2026-06")), m == "2026-07"
    bins = Bins(can[tr], features=MARKET)
    A, b = normal_equations(bins.codes(can[tr]), bins, y[tr])
    cva = bins.codes(can[va])
    mse = [float(np.mean((y[va] - predict(cva, *ridge(A, b, lam), bins)) ** 2)) for lam in LAMBDAS]
    lam = LAMBDAS[int(np.argmin(mse))]
    yx = ex["y"].to_numpy().astype(np.float64)
    mx = ex["month"].to_numpy()
    trx, vax = np.isin(mx, ("2026-05", "2026-06")), mx == "2026-07"
    bx = Bins(ex[trx], features=MARKET + POSITION)
    cx_tr, cx_va = bx.codes(ex[trx]), bx.codes(ex[vax])
    ll = []
    for tau in TAUS:
        w, b0, _ = fit_map(cx_tr, yx[trx], bx, tau)
        pr = np.clip(1 / (1 + np.exp(-predict(cx_va, w, b0, bx))), 1e-6, 1 - 1e-6)
        ll.append(float(-np.mean(yx[vax] * np.log(pr) + (1 - yx[vax]) * np.log(1 - pr))))
    tau = TAUS[int(np.argmin(ll))]
    log.info("lambda %g (MSE %s), tau %g (log loss %s)", lam, np.round(mse, 1), tau, np.round(ll, 4))
    sets = {"A": ("2026-05", "2026-06"), "B": ("2026-05", "2026-06", "2026-07"),
            "C": ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10")}
    models = {"lam": lam, "tau": tau, "mse": mse, "logloss": ll}
    for nm, months in sets.items():
        r = np.isin(m, months)
        cb = Bins(can[r], features=MARKET)
        A, b = normal_equations(cb.codes(can[r]), cb, y[r])
        w, b0 = ridge(A, b, lam)
        rx = np.isin(mx, months)
        xb = Bins(ex[rx], features=MARKET + POSITION)
        wx, b0x, _ = fit_map(xb.codes(ex[rx]), yx[rx], xb, tau)
        models[nm] = {"cancel": {"bins": cb, "w": w, "b0": b0}, "exit": {"bins": xb, "w": wx, "b0": b0x}}
    with open(OUT / "models.pkl", "wb") as f:
        pickle.dump(models, f)


def policy(period: str) -> None:
    with open(OUT / "models.pkl", "rb") as f:
        models = pickle.load(f)
    xs.set_period(period)
    if period == "main":
        combos = [(c, th) for c in CS for th in THETAS]
        plan = {"2026-07": "A", "2026-08": "B", "2026-09": "B", "2026-10": "B"}
        part = OUT / "policy"
    else:
        ch = json.loads((OUT / "choice.json").read_text())
        combos = list(dict.fromkeys([(ch["c"], ch["theta"]), (None, None)]))
        plan = {mo: "C" for mo in xs.SIM_MONTHS}
        part = OUT / "policy_early"
    part.mkdir(exist_ok=True)
    for sym in pd.read_csv(xs.UNIVERSE)["sym"]:
        p = part / f"{sym}.parquet"
        if p.exists():
            continue
        months = [m for m in xs.SIM_MONTHS if m in plan and m in xs.available(sym)]
        if not months:
            continue
        try:
            coin = Coin(sym)
        except FileNotFoundError:
            continue
        T = []
        for mo in months:
            data = month_data(coin, mo)
            if data is None:
                continue
            t, price, px, notional, side, mult = data
            feat, m0 = second_features(coin, mo, t, price, side, notional, mult)
            tr = run_sims(coin, mo, data, feat, m0, models[plan[mo]], combos)
            if tr is not None:
                T.append(tr)
            del data, feat
            gc.collect()
        if T:
            df = pd.concat(T, ignore_index=True)
            df["sym"] = sym
            df.to_parquet(p)
            log.info("%s: %d trips over %d combos", sym, len(df), len(combos))


def summarize(df: pd.DataFrame, start: pd.Timestamp, rng) -> dict:
    p = df["pnl_bp"].to_numpy().astype(np.float64)
    day = ((df["t"].to_numpy() - int(start.timestamp() * 1000)) // 86_400_000)
    b = boot99(p, day, rng)
    dsum = pd.Series(p).groupby(day).sum()
    tot = p.sum()
    return {"trips": len(p), "trips_per_coin_day": len(p) / max(pd.DataFrame({"s": df["sym"], "d": day}).drop_duplicates().shape[0], 1),
            "mean": b[0], "lo99": b[1], "lo95": b[2], "hi95": b[3], "total_bp_per_day": tot / max(dsum.size, 1),
            "win_share": float((p >= 0).mean()), "mean_win": float(p[p >= 0].mean()) if (p >= 0).any() else np.nan,
            "mean_loss": float(p[p < 0].mean()) if (p < 0).any() else np.nan, "by_tp_share": float(df["by_tp"].mean()),
            "defended_share": float(df["defended"].mean()),
            "top5_day_share": float(dsum.nlargest(5).sum() / tot) if tot > 0 else np.nan}


def report(period: str) -> None:
    rng = np.random.default_rng(0)
    xs.set_period(period)
    part = OUT / ("policy" if period == "main" else "policy_early")
    df = pd.concat([pd.read_parquet(p) for p in sorted(part.glob("*.parquet"))], ignore_index=True)
    df["month"] = _month(df["t"].to_numpy())
    first = xs.START + pd.Timedelta(days=int((pd.Timestamp(xs.SIM_MONTHS[0] + "-01", tz="UTC") - xs.START).days)
                                    + xs.SEL_LOOKBACK_D)
    df = df[df["t"] >= int(first.timestamp() * 1000)]
    rows, mo_rows = [], []
    halves = {"valid_2026-07": ["2026-07"], "test_2026-08..10": ["2026-08", "2026-09", "2026-10"]} \
        if period == "main" else {"2025": sorted(df["month"].unique())}
    for (c, th), g in df.groupby(["c", "theta"]):
        for h, ms in halves.items():
            x = g[g["month"].isin(ms)]
            if len(x):
                rows.append({"c": c, "theta": th, "half": h, **summarize(x, xs.START, rng)})
        mo = g.groupby("month")["pnl_bp"].agg(["size", "mean"]).reset_index()
        mo["c"], mo["theta"] = c, th
        mo_rows.append(mo)
    res = pd.DataFrame(rows)
    tag = "" if period == "main" else "_early"
    res.to_csv(OUT / f"result{tag}.csv", index=False)
    pd.concat(mo_rows).to_csv(OUT / f"by_month{tag}.csv", index=False)
    pd.set_option("display.width", 250)
    print(res.round(3).to_string(index=False))
    if period == "main":
        v = res[res["half"] == "valid_2026-07"]
        best = v.loc[v["total_bp_per_day"].idxmax()]
        ch = {"c": None if best["c"] < -0.5 else float(best["c"]), "theta": None if best["theta"] < -0.5 else float(best["theta"])}
        te = res[(res["half"] == "test_2026-08..10") & (res["c"] == best["c"]) & (res["theta"] == best["theta"])].iloc[0]
        ch["pass_test"] = bool(te["trips"] >= MIN_KEPT and te["mean"] > 0 and te["lo99"] > 0)
        (OUT / "choice.json").write_text(json.dumps(ch, indent=1))
        print("chosen on 2026-07:", ch)
        print(te.to_string())
    print(pd.concat(mo_rows).pivot_table(index="month", columns=["c", "theta"], values="mean").round(2).to_string())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "fit", "policy", "report"])
    ap.add_argument("--period", default="main", choices=sorted(xs.PERIODS))
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    if a.cmd == "build":
        build()
    elif a.cmd == "fit":
        fit()
    elif a.cmd == "policy":
        policy(a.period)
    else:
        report(a.period)


if __name__ == "__main__":
    main()
