"""Binance USDⓈ-M public market data: REST (no key) and WebSocket streams.

No credentials are used here. On HTTP 451 / 403 (regional restriction) the client raises
`AccessRestricted` and the caller must stop: do not route around it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)

REST = "https://fapi.binance.com"
WS_MARKET = "wss://fstream.binance.com/market/stream"    # kline, aggTrade
WS_PUBLIC = "wss://fstream.binance.com/public/stream"    # bookTicker


class AccessRestricted(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


class PublicRest:
    def __init__(self, base: str = REST, timeout: float = 10.0, session: requests.Session | None = None):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = "live-momentum/phase1"

    def get(self, path: str, params: dict | None = None, retries: int = 4):
        delay = 1.0
        for k in range(retries):
            try:
                r = self.s.get(self.base + path, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if k == retries - 1:
                    raise
                log.warning("REST %s failed (%s), retrying", path, type(e).__name__)
                time.sleep(delay); delay *= 2
                continue
            if r.status_code in (403, 451):
                raise AccessRestricted(f"{path}: HTTP {r.status_code} (access restricted - do not bypass)")
            if r.status_code == 418:
                raise RateLimited(f"{path}: HTTP 418 (IP banned for rate limits)")
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", delay))
                log.warning("REST %s rate limited, waiting %.0fs", path, wait)
                time.sleep(wait); delay *= 2
                continue
            if r.status_code >= 500 and k < retries - 1:
                time.sleep(delay); delay *= 2
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"REST {path}: retries exhausted")

    def server_time_ms(self) -> int:
        return int(self.get("/fapi/v1/time")["serverTime"])

    def exchange_info(self, symbols) -> dict:
        out = {}
        for s in self.get("/fapi/v1/exchangeInfo")["symbols"]:
            if s["symbol"] in symbols:
                f = {x["filterType"]: x for x in s["filters"]}
                out[s["symbol"]] = dict(
                    status=s["status"], contract=s["contractType"],
                    tick=float(f["PRICE_FILTER"]["tickSize"]), step=float(f["LOT_SIZE"]["stepSize"]),
                    market_step=float(f["MARKET_LOT_SIZE"]["stepSize"]),
                    min_qty=float(f["LOT_SIZE"]["minQty"]),
                    min_notional=float(f.get("MIN_NOTIONAL", {}).get("notional", 0.0)))
        return out

    def klines(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Closed 1m bars with open_time in [start, end). Indexed by open_time (UTC)."""
        rows, t = [], int(start.value // 1_000_000)
        stop = int(end.value // 1_000_000)
        while t < stop:
            batch = self.get("/fapi/v1/klines", dict(symbol=symbol, interval="1m", startTime=t,
                                                     endTime=stop - 1, limit=1500))
            if not batch:
                break
            rows += batch
            t = int(batch[-1][0]) + 60_000
            if len(batch) < 1500:
                break
        return klines_frame(rows, now_ms=int(time.time() * 1000))

    def funding(self, symbol: str, start: pd.Timestamp) -> pd.DataFrame:
        rows, t = [], int(start.value // 1_000_000)
        while True:
            batch = self.get("/fapi/v1/fundingRate", dict(symbol=symbol, startTime=t, limit=1000))
            rows += batch
            if len(batch) < 1000:
                break
            t = int(batch[-1]["fundingTime"]) + 1
        if not rows:
            return pd.DataFrame(columns=["time", "rate"])
        return pd.DataFrame({"time": pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms", utc=True).floor("min"),
                             "rate": [float(r["fundingRate"]) for r in rows]})


def klines_frame(rows, now_ms: int | None = None) -> pd.DataFrame:
    """REST kline rows -> research column layout. Bars not closed yet (close_time >= now) dropped."""
    if now_ms is not None:
        rows = [r for r in rows if int(r[6]) < now_ms]
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "quote_volume",
                                     "taker_buy_volume"], index=pd.DatetimeIndex([], tz="UTC", name="open_time"))
    df = pd.DataFrame({
        "open_time": pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True),
        "open": [float(r[1]) for r in rows], "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows], "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows], "quote_volume": [float(r[7]) for r in rows],
        "taker_buy_volume": [float(r[9]) for r in rows]})
    return df.drop_duplicates("open_time").set_index("open_time").sort_index()


def ws_kline_row(k: dict) -> tuple[pd.Timestamp, dict]:
    """Closed kline from the stream payload `k` -> (open_time, row)."""
    return (pd.Timestamp(int(k["t"]), unit="ms", tz="UTC"),
            dict(open=float(k["o"]), high=float(k["h"]), low=float(k["l"]), close=float(k["c"]),
                 volume=float(k["v"]), quote_volume=float(k["q"]), taker_buy_volume=float(k["V"])))


def ws_status(e: BaseException) -> int | None:
    """HTTP status of a rejected WebSocket handshake (websockets >= 14: e.response.status_code;
    older: e.status_code), else None."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    if code is None:
        code = getattr(e, "status_code", None)
    return int(code) if isinstance(code, int) else None


async def stream(url: str, streams: list[str], on_message, stop: asyncio.Event,
                 on_connect=None, max_backoff: float = 30.0):
    """Combined-stream consumer with reconnects. on_message(stream_name, data, recv_ms)."""
    import websockets
    full = f"{url}?streams={'/'.join(streams)}"
    backoff = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(full, open_timeout=10, ping_interval=20, ping_timeout=20,
                                          max_size=2 ** 22) as ws:
                backoff = 1.0
                if on_connect:
                    on_connect(url)
                opened = time.monotonic()
                while not stop.is_set():
                    if time.monotonic() - opened > 23 * 3600:      # Binance drops after 24h
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        log.warning("no message for 30s on %s, reconnecting", url)
                        break
                    msg = json.loads(raw)
                    if "stream" in msg:
                        on_message(msg["stream"], msg["data"], int(time.time() * 1000))
        except Exception as e:                                     # noqa: BLE001 - reconnect on anything
            if ws_status(e) in (403, 451):
                raise AccessRestricted(f"websocket {url}: {e}") from e
            log.warning("stream %s error %s: %s; reconnect in %.0fs", url, type(e).__name__, e, backoff)
        if not stop.is_set():
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)
