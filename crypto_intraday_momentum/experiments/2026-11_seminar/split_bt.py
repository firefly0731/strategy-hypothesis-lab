"""Entries checked every E minutes, exits/flips only on the X-minute grid (default 30).
Patches a copy of backtest.run_backtest: while a position is open, decision minutes that
are not on the exit grid are skipped (no stop, no flip). Reuses IV_<sym>.pkl sessions."""
import inspect, json, sys, textwrap
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import crypto_intraday_momentum.backtest as bt
import crypto_intraday_momentum.sizing as sz
from crypto_intraday_momentum.backtest import Config
from crypto_intraday_momentum.cpcv import EXEC
from crypto_intraday_momentum.data import load_funding
from crypto_intraday_momentum.run import TICKS
from crypto_intraday_momentum.signals import compute_signals
from crypto_intraday_momentum.sizing import unit_trades
from crypto_intraday_momentum.run_sizing import build_portfolio, RULES

OUT = sys.argv[1]; PPY = 252
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

src = inspect.getsource(bt.run_backtest)
anchor = "            p, ub, lb, vw = s.px[i, j], s.ub[i, j], s.lb[i, j], s.vwap[i, j]\n"
assert src.count(anchor) == 1
src = src.replace(anchor, anchor + "            if pos != 0 and EXIT_EVERY and t % EXIT_EVERY != 0:\n                continue\n")
src = src.replace("def run_backtest(", "def run_backtest_split(")
ns = dict(vars(bt)); ns["EXIT_EVERY"] = None
exec(compile(src, "split", "exec"), ns)

# (entry interval, first decision minute, exit grid)
VARIANTS = {"30/30": (30, 30, None), "15/30": (15, 30, 30), "15from15/30": (15, 15, 30),
            "5/30": (5, 30, 30), "5from5/30": (5, 5, 30), "5/15": (5, 30, 15)}


def mt(r):
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1
    return dict(cagr=eq.iloc[-1] ** (PPY / len(r)) - 1, vol=r.std() * np.sqrt(PPY),
                sharpe=r.mean() / r.std() * np.sqrt(PPY), mdd=dd.min())


D = {s: pd.read_pickle(f"{OUT}/IV_{s}.pkl") for s in SYMS}
F = {s: load_funding(s, "2021-01", "2026-10") for s in SYMS}
sz.run_backtest = ns["run_backtest_split"]
res = {}
for k, (iv, first, xe) in VARIANTS.items():
    ns["EXIT_EVERY"] = xe
    data = {}
    for s in SYMS:
        m = D[s]["m"]
        cfg = Config(tick=TICKS.get(s, 0.01), **EXEC["maker_chase"], **RULES)
        data[s] = (m, unit_trades(m, compute_signals(m, interval=iv, first=first), cfg, F[s]), D[s]["rv"])
    if k == "30/30":   # patched loop with EXIT_EVERY=None must equal the stored production run
        for s in SYMS:
            a, b = data[s][1], D[s]["t"]["30m"]
            assert len(a) == len(b) and np.allclose(a.pnl, b.pnl), s
    T = pd.concat([t.assign(sym=s) for s, (_, t, _) in data.items()])
    U = pd.DataFrame({s: t.groupby("sess_idx").ret_notional.sum().reindex(range(D[s]["m"].n)).fillna(0.0)
                      .set_axis(D[s]["m"].dates) for s, (_, t, _) in data.items()}).fillna(0.0).iloc[31 + 60:]
    u = U.mean(axis=1)
    r, _ = build_portfolio(data, "rv24", "equal", 0.25, 3.0, 0.15, scale_cap=20.0)
    r = r.iloc[60:]
    weeks = len(u) / PPY * 52
    res[k] = dict(unit=mt(u), prod=mt(r), trades_per_week=len(T[T.date >= u.index[0]]) / weeks,
                  net_bp=T.ret_notional.mean() * 1e4, gross_bp=(T.gross / T.notional).mean() * 1e4,
                  win=(T.pnl > 0).mean(), hold_min=T.hold_min.mean(), stop_share=(T.exit_reason == "stop").mean(),
                  yearly_unit=u.groupby(u.index.year).apply(lambda x: x.mean() / x.std() * np.sqrt(PPY)).round(2).to_dict())
    print(k, {a: round(float(b), 3) for a, b in res[k].items() if a not in ("unit", "prod", "yearly_unit")})
    print("   unit", {a: round(float(b), 3) for a, b in res[k]["unit"].items()}, " prod", {a: round(float(b), 3) for a, b in res[k]["prod"].items()})
    print("   yearly unit SR", res[k]["yearly_unit"])
json.dump(res, open(f"{OUT}/split.json", "w"), default=str, indent=1)
