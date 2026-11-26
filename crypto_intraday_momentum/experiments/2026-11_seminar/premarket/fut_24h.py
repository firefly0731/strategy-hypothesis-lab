"""Same noise-band rules on NQ=F / ES=F hourly: 24h Globex session vs regular-hours window.
globex : session 18:00 ET (prev day) .. 17:00 ET, 23 hourly bars, entries in the first 69% (like 14:00 of 09:30-16:00)
regular: session 10:00 .. 16:00 ET on the futures (bars on the hour, so anchor 10:00), entries through 14:00
Cost 1 bp per side. 1x notional. Fill at decision bar close."""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
RAW = sys.argv[1]
ET = "America/New_York"


def sessions(d, mode):
    d = d[(d.index.minute == 0)]
    out = []
    if mode == "globex":
        start = d.index[d.index.hour == 18]
        for s in start:
            x = d[(d.index >= s) & (d.index < s + pd.Timedelta(hours=23))]
            if len(x) >= 20 and s.weekday() in (6, 0, 1, 2, 3):      # Sun..Thu evening opens
                full = pd.date_range(s, periods=23, freq="h")
                x = x.reindex(full)
                x["close"] = x["close"].ffill(); x["volume"] = x["volume"].fillna(0)
                for c in ("open", "high", "low"):
                    x[c] = x[c].fillna(x["close"])
                if x.close.notna().all():
                    out.append(x)
    else:
        for day, x in d.groupby(d.index.date):
            x = x[(x.index.hour >= 10) & (x.index.hour <= 15)]
            if len(x) == 6:
                out.append(x)
    return out


def run(S, entry_frac=0.69, cost=1.0, f=0.6):
    O = np.array([x.open.iloc[0] for x in S]); C = np.array([x.close.to_numpy() for x in S])
    tp = np.array([((x.high + x.low + x.close) / 3).to_numpy() for x in S]); V = np.array([x.volume.to_numpy() for x in S], float)
    vw = np.cumsum(tp * V, 1) / np.maximum(np.cumsum(V, 1), 1e-9)
    nb = C.shape[1]; last_entry = int(np.floor(nb * entry_frac)) - 1
    mv = np.abs(C / O[:, None] - 1); res = []
    for i in range(15, len(S)):
        sig = mv[i - 14:i].mean(0); pc = C[i - 1, -1]
        ub, lb = max(O[i], pc) * (1 + sig), min(O[i], pc) * (1 - sig)
        pos = 0; e = 0; r = 0; n = 0
        for k in range(nb):
            c = C[i, k]
            if pos > 0 and c < max(ub[k], vw[i, k]) or pos < 0 and c > min(lb[k], vw[i, k]):
                r += pos * (c / e - 1) - cost / 1e4; pos = 0
            if pos == 0 and k <= last_entry and k < nb - 1:
                if c > ub[k] and c > vw[i, k] * (1 + f * sig[k]): pos, e, n = 1, c, n + 1; r -= cost / 1e4
                elif c < lb[k] and c < vw[i, k] * (1 - f * sig[k]): pos, e, n = -1, c, n + 1; r -= cost / 1e4
        if pos: r += pos * (C[i, -1] / e - 1) - cost / 1e4
        res.append((S[i].index[-1], r, n))
    R = pd.DataFrame(res, columns=["d", "r", "n"]).set_index("d"); r = R.r
    yr = r.groupby(r.index.year).sum().mul(100).round(1).to_dict()
    return f"days {len(r)}, trades {R.n.sum()}, ann {r.mean()*252*100:+.1f}%, Sharpe {r.mean()/r.std()*np.sqrt(252):+.2f}, t {r.mean()/r.std()*np.sqrt(len(r)):+.2f}, by year % {yr}"


for sym in ("NQ", "ES"):
    d = pd.read_parquet(f"{RAW}/{sym}_60m.parquet"); d.index = d.index.tz_convert(ET); d = d[d.index < "2026-11-23 17:00"]
    for mode in ("globex", "regular"):
        for f in (0.0, 0.6):
            print(f"{sym} {mode:7s} f={f}: {run(sessions(d, mode), f=f)}")
