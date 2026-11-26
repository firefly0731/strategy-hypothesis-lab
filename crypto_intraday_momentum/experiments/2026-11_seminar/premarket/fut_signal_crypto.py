"""Noise-band signal computed on NQ=F / ES=F hourly bars, positions taken in Binance BTC/ETH/SOL perps.
Position path is decided on the futures bar closes (same rules as fut_24h.py); the P&L is the crypto
price change between the same timestamps (crypto price at t = open of the 1m kline at t).
Crypto cost 3 bp per side (maker_chase-ish blend). 1x notional per symbol, symbols averaged per day.
Baseline: the same rules computed on the crypto's own hourly bars over the same windows."""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[2])
from fut_24h import sessions
from crypto_intraday_momentum.data import load_klines
RAW = sys.argv[1]; ET = "America/New_York"; COST = 3.0


def positions(S, f=0.6, entry_frac=0.69):
    """per session: list of (k, pos after decision at close of bar k)"""
    O = np.array([x.open.iloc[0] for x in S]); C = np.array([x.close.to_numpy() for x in S])
    tp = np.array([((x.high + x.low + x.close) / 3).to_numpy() for x in S]); V = np.array([x.volume.to_numpy() for x in S], float)
    vw = np.cumsum(tp * V, 1) / np.maximum(np.cumsum(V, 1), 1e-9)
    nb = C.shape[1]; last = int(np.floor(nb * entry_frac)) - 1; mv = np.abs(C / O[:, None] - 1)
    out = {}
    for i in range(15, len(S)):
        sig = mv[i - 14:i].mean(0); pc = C[i - 1, -1]
        ub, lb = max(O[i], pc) * (1 + sig), min(O[i], pc) * (1 - sig)
        pos = 0; path = []
        for k in range(nb):
            c = C[i, k]
            if pos > 0 and c < max(ub[k], vw[i, k]) or pos < 0 and c > min(lb[k], vw[i, k]):
                pos = 0
            if pos == 0 and k <= last and k < nb - 1:
                if c > ub[k] and c > vw[i, k] * (1 + f * sig[k]): pos = 1
                elif c < lb[k] and c < vw[i, k] * (1 - f * sig[k]): pos = -1
            if k == nb - 1: pos = 0
            path.append(pos)
        out[S[i].index[0]] = (S[i].index + pd.Timedelta(hours=1), np.array(path))   # decision times = bar ends
    return out


def pnl(paths, px):
    rows = []
    for s0, (times, path) in paths.items():
        p = px.reindex(times).to_numpy()
        if not np.isfinite(p).all():
            continue
        prev = np.r_[0, path[:-1]]
        r = np.sum(prev[1:] * (p[1:] / p[:-1] - 1)) - np.abs(np.diff(np.r_[0, path])).sum() * COST / 1e4
        rows.append((s0, r, int((np.diff(np.r_[0, path]) != 0).sum())))
    return pd.DataFrame(rows, columns=["s", "r", "chg"]).set_index("s")


def stats(R):
    r = R.r
    yr = r.groupby(r.index.year).sum().mul(100).round(1).to_dict()
    return f"days {len(r):3d} ann {r.mean()*252*100:+6.1f}% Sharpe {r.mean()/r.std()*np.sqrt(252):+.2f} t {r.mean()/r.std()*np.sqrt(len(r)):+.2f} by year % {yr}"


px, own = {}, {}
for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    k = load_klines(s, "2024-07", "2026-10"); k = k.set_index("open_time") if "open_time" in k.columns else k
    k.index = k.index.tz_convert(ET); px[s] = k["open"]
    h = k.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    own[s] = h
for fut in ("NQ", "ES"):
    d = pd.read_parquet(f"{RAW}/{fut}_60m.parquet"); d.index = d.index.tz_convert(ET); d = d[d.index < "2026-10-31"]
    for mode in ("globex", "regular"):
        for f in (0.0, 0.6):
            P = positions(sessions(d, mode), f=f)
            R = pd.concat([pnl(P, px[s]) for s in px], axis=1, keys=list(px)).xs("r", axis=1, level=1).dropna().mean(1).to_frame("r")
            print(f"signal {fut} {mode:7s} f={f} -> crypto: {stats(R)}")
for mode in ("globex", "regular"):
    Rs = []
    for s in px:
        P = positions(sessions(own[s], mode), f=0.6)     # crypto's own bars, same clock windows
        Rs.append(pnl(P, px[s]).r)
    R = pd.concat(Rs, axis=1).dropna().mean(1).to_frame("r")
    print(f"baseline crypto-own {mode:7s} f=0.6 -> crypto: {stats(R)}")
