import json, sys, urllib.request
import pandas as pd
out = sys.argv[1]
for sym in ("SPY", "QQQ"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=60m&range=730d&includePrePost=false"
    d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
    r = d["chart"]["result"][0]; q = r["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")},
                      index=pd.to_datetime(r["timestamp"], unit="s", utc=True)).dropna(subset=["close"])
    df.to_parquet(f"{out}/{sym}_60m.parquet")
    et = df.index.tz_convert("America/New_York")
    print(sym, len(df), et.min(), et.max(), sorted(set(et.strftime("%H:%M")))[:8])
