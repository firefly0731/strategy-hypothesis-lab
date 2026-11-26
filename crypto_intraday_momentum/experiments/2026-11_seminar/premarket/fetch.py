"""Download Yahoo 60m (730d) and 5m (60d) bars for NQ=F, ES=F into a parquet. Parse JSON only."""
import json, sys, urllib.request
import pandas as pd
out = sys.argv[1]
for sym in ("NQ=F", "ES=F"):
    for iv, rng in (("60m", "730d"), ("5m", "60d")):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={iv}&range={rng}&includePrePost=true"
        d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
        r = d["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")},
                          index=pd.to_datetime(r["timestamp"], unit="s", utc=True)).dropna(subset=["close"])
        fn = f"{out}/{sym[:2]}_{iv}.parquet"
        df.to_parquet(fn)
        print(sym, iv, len(df), df.index.min(), df.index.max())
