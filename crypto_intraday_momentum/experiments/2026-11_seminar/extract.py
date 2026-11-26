"""Seminar numbers from the production configuration (fixed adopted rules, whole period).
rv24 sizing, equal weight, 25% portfolio vol target (cap 20), 3x per-trade cap, dd throttle 15%."""
import json, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from crypto_intraday_momentum.run_sizing import build_portfolio, load_symbol
from crypto_intraday_momentum.data import load_klines

OUT = sys.argv[1]; PPY = 252
def mt(r):
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1
    yrs = len(r) / PPY
    return dict(cagr=eq.iloc[-1] ** (1 / yrs) - 1, vol=r.std() * np.sqrt(PPY), sharpe=r.mean() / r.std() * np.sqrt(PPY),
                mdd=dd.min(), pos_days=(r > 0).mean(), flat_days=(r == 0).mean(), days=len(r),
                t=r.mean() / r.std() * np.sqrt(len(r)))
res = {}
for setname, syms in (("disc", ["BTCUSDT", "ETHUSDT", "SOLUSDT"]), ("hold", ["BNBUSDT", "XRPUSDT", "DOGEUSDT"])):
    for ex in ("maker_chase", "taker"):
        data = {s: load_symbol(s, "2021-01", "2026-10", ex) for s in syms}
        r, L = build_portfolio(data, "rv24", "equal", 0.25, 3.0, 0.15, scale_cap=20.0)
        r = r.iloc[60:]
        key = f"{setname}_{ex}"
        res[key] = dict(metrics=mt(r), yearly=r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1).to_dict(),
                        eq=((1 + r).cumprod()).resample("W").last().round(4).to_dict())
        if key == "disc_maker_chase":
            traded = r[r != 0]
            srt = traded.sort_values(ascending=False)
            tot = r.sum()
            res["conc"] = dict(top10pct_share=srt.iloc[:int(len(srt) * .1)].sum() / tot,
                               top5pct_share=srt.iloc[:int(len(srt) * .05)].sum() / tot,
                               traded_days=len(traded), win_rate_traded=(traded > 0).mean(),
                               avg_win=traded[traded > 0].mean(), avg_loss=traded[traded < 0].mean())
            res["hist"] = np.histogram(traded.clip(-0.06, 0.06) * 100, bins=24, range=(-6, 6))[0].tolist()
            T = pd.concat([t.assign(sym=s) for s, (m, t, rv) in data.items()])
            T["bp"] = T["ret_notional"] * 1e4
            T["gross_bp"] = T["gross"] / T["notional"] * 1e4
            T["time"] = (pd.Timestamp("2000-01-01 09:30") + pd.to_timedelta(T["dec_min"], "min")).dt.strftime("%H:%M")
            res["by_time"] = T.groupby("time").agg(n=("bp", "size"), bp=("bp", "mean")).round(1).reset_index().to_dict("records")
            res["by_side"] = T.groupby(np.where(T.side > 0, "long", "short")).bp.mean().round(1).to_dict()
            res["by_sym"] = T.groupby("sym").bp.mean().round(1).to_dict()
            res["trade"] = dict(n=len(T), net_bp=T.bp.mean(), gross_bp=T.gross_bp.mean(), win=(T.bp > 0).mean(),
                                hold_min=T.hold_min.mean() if "hold_min" in T else None,
                                maker_entry=T["entry_maker"].mean() if "entry_maker" in T else None)
            res["cols"] = list(T.columns)
# BTC buy & hold over the same weeks, for scale
k = load_klines("BTCUSDT", "2021-01", "2026-10"); k = k.set_index("open_time") if "open_time" in k.columns else k
c = k["close"].resample("W").last(); c.index = c.index.tz_localize(None)
idx = pd.DatetimeIndex(list(res["disc_maker_chase"]["eq"].keys()))
c = c.reindex(idx, method="ffill"); res["btc_eq"] = (c / c.iloc[0]).round(4).tolist()
def clean(o):
    if isinstance(o, dict): return {str(k)[:10]: clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)): return o.item()
    return o
json.dump(clean(res), open(f"{OUT}/deck.json", "w"), default=str, indent=1)
for k2 in ("disc_maker_chase", "disc_taker", "hold_maker_chase", "hold_taker"):
    print(k2, {a: round(b, 4) for a, b in res[k2]["metrics"].items()}, {y: round(v, 3) for y, v in res[k2]["yearly"].items()})
print("conc", res["conc"]); print("trade", res["trade"]); print("by_side", res["by_side"], "by_sym", res["by_sym"])
print("by_time", res["by_time"]); print("cols", res["cols"])
