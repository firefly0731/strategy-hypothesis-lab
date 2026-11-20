# data_inbox

Put manually downloaded Binance USDⓈ-M 1-minute klines here when the public archive has not been
published yet. Accepted file names (one file per symbol per UTC day):

- `BTCUSDT-1m-2026-11-19.json`: the raw response of
  `https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&startTime=<ms>&endTime=<ms>&limit=1500`
- `BTCUSDT-1m-2026-11-19.csv` or `.zip`: the data.binance.vision daily file

`crypto_intraday_momentum/data.py` uses these files only when the archive returns 404.
