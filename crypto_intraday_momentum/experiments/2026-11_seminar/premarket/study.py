"""CME index futures (NQ=F, ES=F; Yahoo 60m) as signals for the crypto noise-band strategy.

Fixed BEFORE looking at results (2026-11-24):
  Data: Yahoo 60m continuous front month, bars on the ET hour. At a crypto decision time T the
  latest usable futures price is F(floor_hour(T)) (close of the bar ending then). No look-ahead.
  Sample: NYSE sessions 2024-07-25 .. 2026-10-30 (Yahoo 730-day limit, 14-session warm-up).
  Trades: production backtest (maker_chase, 14:00 cutoff, 0.6 sigma VWAP), run on 2021-01..2026-10
  and filtered to the sample. Discovery = BTC/ETH/SOL, hold-out = BNB/XRP/DOGE.
  H1 agreement filter: agree = sign(F(floor_hour T)/F(09:00) - 1) == trade side.
     Stat: net_bps(agree) - net_bps(disagree), Welch t.
  H2 futures breakout as trigger: at H in 10:00..15:00 (entries only <= 14:00 like the strategy),
     move_H = F(H)/F(09:00)-1, sigma_H = mean |move_H| over the previous 14 sessions; first H with
     |move_H| > sigma_H -> crypto position sign(move_H) from crypto price at H to 16:00 close.
     Net = gross - 8 bp (taker round trip). Stat: mean net bp, t over days (symbols averaged per day).
  H3 gap filter: gap = F(09:00)/F(prev 16:00) - 1. Stat: net_bps(top |gap| quintile) - rest, Welch t.
  Pass (worth a proper study): |t| >= 2.5 in discovery AND same sign with |t| >= 1.5 in hold-out,
  for the same futures contract. 3 hypotheses x 2 contracts = 6 tests, hence 2.5 not 2.
  Anything else = no evidence. Hourly data and ~570 sessions make this a weak first look.
"""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from crypto_intraday_momentum.analyze_trades import run as run_trades
from crypto_intraday_momentum.data import load_klines

RAW = sys.argv[1]
ET = "America/New_York"
S0, S1 = pd.Timestamp("2024-07-25"), pd.Timestamp("2026-10-30")
SETS = {"discovery": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "holdout": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}


def fut(name):
    d = pd.read_parquet(f"{RAW}/{name}_60m.parquet")
    d = d[(d.index.minute == 0) & (d["volume"] > 0)]
    et = d.index.tz_convert(ET)
    return pd.Series(d["open"].to_numpy(), index=et)       # price AT the bar start (= prev bar close)


def welch(a, b):
    return (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))


def tday(x):
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))


def F_at(F, day, hhmm):
    return F.get(pd.Timestamp(f"{day.date()} {hhmm}", tz=ET), np.nan)


trades = {}
for k, syms in SETS.items():
    T = run_trades(syms, "2021-01", "2026-10")
    T["d"] = pd.to_datetime(T["date"])
    trades[k] = T[(T.d >= S0) & (T.d <= S1)].copy()
    print(f"{k}: {len(trades[k])} trades in sample, mean net {trades[k].net_bps.mean():+.1f} bp", flush=True)

closes = {}
for syms in SETS.values():
    for s in syms:
        k = load_klines(s, "2024-07", "2026-10")
        k = k.set_index("open_time") if "open_time" in k.columns else k
        closes[s] = (k["open"], k["close"])

res = []
for fname in ("NQ", "ES"):
    F = fut(fname)
    days = sorted({d for T in trades.values() for d in T.d})
    for setname, T in trades.items():
        T = T.copy()
        dec = pd.to_datetime(T["d"].dt.strftime("%Y-%m-%d") + " 09:30").dt.tz_localize(ET) + pd.to_timedelta(T["dec_min"], "min")
        fh = dec.dt.floor("h")
        f_now = np.array([F.get(x, np.nan) for x in fh])
        f_9 = np.array([F_at(F, d, "09:00") for d in T.d])
        T["agree"] = np.sign(f_now / f_9 - 1) == T["side"].to_numpy()
        ok = np.isfinite(f_now / f_9)
        a, b = T[ok & T.agree].net_bps, T[ok & ~T.agree].net_bps
        res.append(("H1 agree-filter", fname, setname, f"agree n={len(a)} {a.mean():+.1f}bp / disagree n={len(b)} {b.mean():+.1f}bp", welch(a, b)))
        # H3
        prevd = {d: p for p, d in zip(days[:-1], days[1:])}
        g = {d: F_at(F, d, "09:00") / F_at(F, prevd[d], "16:00") - 1 for d in days if d in prevd}
        T["gap"] = T.d.map(g)
        G = T.dropna(subset=["gap"])
        q = G.gap.abs() >= G.gap.abs().quantile(0.8)
        res.append(("H3 big |gap|", fname, setname, f"top20% n={q.sum()} {G[q].net_bps.mean():+.1f}bp / rest {G[~q].net_bps.mean():+.1f}bp", welch(G[q].net_bps, G[~q].net_bps)))
    # H2 event study
    hours = ["10:00", "11:00", "12:00", "13:00", "14:00"]
    mv = pd.DataFrame({h: [F_at(F, d, h) / F_at(F, d, "09:00") - 1 for d in days] for h in hours}, index=days)
    sig = mv.abs().rolling(14).mean().shift(1)
    ev = []
    for d in days:
        for h in hours:
            if np.isfinite(sig.loc[d, h]) and abs(mv.loc[d, h]) > sig.loc[d, h]:
                ev.append((d, h, np.sign(mv.loc[d, h]))); break
    for setname, syms in SETS.items():
        per_day = []
        for d, h, sd in ev:
            r = []
            for s in syms:
                o, c = closes[s]
                t_in = pd.Timestamp(f"{d.date()} {h}", tz=ET).tz_convert("UTC")
                t_out = pd.Timestamp(f"{d.date()} 15:59", tz=ET).tz_convert("UTC")
                if t_in in o.index and t_out in c.index:
                    r.append(sd * (c[t_out] / o[t_in] - 1) * 1e4 - 8)
            if r:
                per_day.append(np.mean(r))
        x = pd.Series(per_day)
        res.append(("H2 fut-breakout trigger", fname, setname, f"events={len(x)} net {x.mean():+.1f}bp/day", tday(x)))

print("\n| hypothesis | futures | set | detail | t |\n|---|---|---|---|---|")
for h, f, s, det, t in res:
    print(f"| {h} | {f} | {s} | {det} | {t:+.2f} |")
