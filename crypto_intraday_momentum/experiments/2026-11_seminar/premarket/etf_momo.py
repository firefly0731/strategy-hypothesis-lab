"""Noise-band intraday momentum on SPY/QQQ (proxies for ES/NQ) with hourly decisions, vs BTC/ETH/SOL same rules.
Bars 09:30..15:30 ET (7 per day, early closes skipped). Decisions at closes 10:30..15:30.
sigma_k = mean |C_k/O - 1| over prior 14 days. UB = max(O, prevC)(1+s), LB = min(O, prevC)(1-s).
Entry (closes 10:30..13:30 only, cutoff 14:00): long C>UB and C>VWAP(1+f*s); short mirror. f = 0 (paper) or 0.6 (ours).
Exit: long when C < max(UB, VWAP) (short mirror), else at 16:00. Fill at the decision bar close. 1x notional."""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
RAW = sys.argv[1]
ET = "America/New_York"


def etf(sym):
    d = pd.read_parquet(f"{RAW}/{sym}_60m.parquet")
    d.index = d.index.tz_convert(ET)
    return d


def crypto(sym):
    from crypto_intraday_momentum.data import load_klines
    k = load_klines(sym, "2023-12", "2026-10")
    k = k.set_index("open_time") if "open_time" in k.columns else k
    k.index = k.index.tz_convert(ET)
    k = k.between_time("09:30", "15:59")
    g = k.groupby(k.index.floor("D"))
    rows = []
    for day, x in g:
        if len(x) < 390:
            continue
        for b in range(7):
            s = x.iloc[b * 60:(b + 1) * 60] if b < 6 else x.iloc[360:390]
            rows.append((s.index[0], s.open.iloc[0], s.high.max(), s.low.min(), s.close.iloc[-1], s.volume.sum()))
    return pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"]).set_index("t")


def matrix(d, only=None):
    d = d[d.index.strftime("%H:%M").isin(["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"])]
    days = []
    for day, x in d.groupby(d.index.date):
        if len(x) == 7 and (only is None or pd.Timestamp(day) in only):
            days.append((pd.Timestamp(day), x))
    O = np.array([x.open.iloc[0] for _, x in days])
    C = np.array([x.close.to_numpy() for _, x in days])
    tp = np.array([((x.high + x.low + x.close) / 3).to_numpy() for _, x in days])
    V = np.array([x.volume.to_numpy() for _, x in days]).astype(float)
    vw = np.cumsum(tp * V, 1) / np.maximum(np.cumsum(V, 1), 1e-9)
    return [d for d, _ in days], O, C, vw


def backtest(days, O, C, vw, f=0.6, cost_bp=1.0):
    n = len(days)
    mv = np.abs(C / O[:, None] - 1)
    out = []
    for i in range(15, n):
        sig = mv[i - 14:i].mean(0)
        pc = C[i - 1, -1]
        ub, lb = max(O[i], pc) * (1 + sig), min(O[i], pc) * (1 - sig)
        pos, entry, r = 0, 0.0, 0.0
        ntr = 0
        for k in range(7):
            c = C[i, k]
            if k == 0:
                continue
            if pos > 0 and c < max(ub[k], vw[i, k]) or pos < 0 and c > min(lb[k], vw[i, k]):
                r += pos * (c / entry - 1) - cost_bp / 1e4; pos = 0
            if pos == 0 and k <= 4:
                if c > ub[k] and c > vw[i, k] * (1 + f * sig[k]):
                    pos, entry = 1, c; r -= cost_bp / 1e4; ntr += 1
                elif c < lb[k] and c < vw[i, k] * (1 - f * sig[k]):
                    pos, entry = -1, c; r -= cost_bp / 1e4; ntr += 1
        if pos:
            r += pos * (C[i, -1] / entry - 1) - cost_bp / 1e4
        out.append((days[i], r, ntr))
    return pd.DataFrame(out, columns=["d", "r", "n"]).set_index("d")


def stats(R):
    r = R.r
    sr = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    yr = r.groupby(r.index.year).apply(lambda x: x.sum() * 100).round(1).to_dict()
    tr = R.n.sum()
    return f"days {len(r)}, trades {tr}, net/trade {r.sum()/max(tr,1)*1e4:+.1f}bp, ann {r.mean()*252*100:+.1f}%, Sharpe {sr:+.2f}, t {r.mean()/r.std()*np.sqrt(len(r)):+.2f}, by year % {yr}"


src = {"SPY": (etf("SPY"), 1.0), "QQQ": (etf("QQQ"), 1.0)}
for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    src[s] = (crypto(s), 3.0)
nyse = set(matrix(src["SPY"][0])[0])
for name, (d, cost) in src.items():
    m = matrix(d, nyse)
    for f in (0.0, 0.6):
        print(f"{name:8s} f={f}: {stats(backtest(*m, f=f, cost_bp=cost))}")
    print(f"{name:8s} gross f=0.6: {stats(backtest(*m, f=0.6, cost_bp=0.0))}")
