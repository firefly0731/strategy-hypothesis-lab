"""Binance USD-M futures public market-data collector (hftbacktest-compatible raw format).

Writes one gzip file per symbol per UTC day:   <out>/<YYYYMMDD>/<symbol>.gz
Each line:   <local_timestamp_ns (19 digits)> <raw JSON>
  * websocket messages are written verbatim in combined-stream form
    {"stream": "btcusdc@depth@0ms", "data": {...}}
  * REST depth snapshots (/fapi/v1/depth) are written as their raw JSON
    (hftbacktest.data.utils.binancefutures.convert turns them into DEPTH_CLEAR + DEPTH_SNAPSHOT)

So the output feeds directly into:
    from hftbacktest.data.utils import binancefutures
    binancefutures.convert("<out>/20261120/btcusdc.gz", output_filename="btcusdc_20261120.npz", opt="t")

Public endpoints only (no API key). Run it on your own server, in a jurisdiction where Binance
futures market data may be accessed, ideally close to the matching engine (AWS ap-northeast-1).

    python -m crypto_mm.collector --config crypto_mm/collector.toml
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import os
import random
import signal
import time
import tomllib
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import websockets

log = logging.getLogger("collector")


# ----------------------------------------------------------------------------- config

@dataclass
class Config:
    out_dir: str = "./md_raw"
    ws_url: str = "wss://fstream.binance.com/stream"
    rest_url: str = "https://fapi.binance.com"
    # symbol -> list of streams (without the "<symbol>@" prefix)
    symbols: dict[str, list[str]] = field(default_factory=lambda: {
        "BTCUSDC": ["depth@0ms", "trade", "bookTicker"],
        "BTCUSDT": ["trade", "bookTicker"],
    })
    snapshot_limit: int = 1000            # /fapi/v1/depth limit (weight 20 at 1000)
    snapshot_every_s: int = 3600          # periodic resync snapshot even without gaps
    reconnect_every_s: int = 23 * 3600    # Binance drops connections after 24h
    flush_every_s: float = 1.0
    stats_every_s: int = 60
    max_streams_per_conn: int = 150       # Binance limit is 200 per connection

    @classmethod
    def load(cls, path: str | None) -> "Config":
        if not path:
            return cls()
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        c = cls()
        for k, v in raw.items():
            if k == "symbols":
                c.symbols = {s.upper(): list(st) for s, st in v.items()}
            elif hasattr(c, k):
                setattr(c, k, v)
        return c


# ----------------------------------------------------------------------------- writer

class DailyGzipWriter:
    """Append-mode gzip per (symbol, UTC day). Appending creates a new gzip member,
    which gzip readers (incl. hftbacktest's convert) read transparently."""

    def __init__(self, out_dir: str):
        self.out = Path(out_dir)
        self.files: dict[str, tuple[str, gzip.GzipFile]] = {}
        self.bytes = defaultdict(int)

    def _day(self, ts_ns: int) -> str:
        return time.strftime("%Y%m%d", time.gmtime(ts_ns // 1_000_000_000))

    def write(self, symbol: str, ts_ns: int, raw: str) -> None:
        day = self._day(ts_ns)
        cur = self.files.get(symbol)
        if cur is None or cur[0] != day:
            if cur is not None:
                cur[1].close()
            p = self.out / day / f"{symbol.lower()}.gz"
            p.parent.mkdir(parents=True, exist_ok=True)
            self.files[symbol] = (day, gzip.open(p, "at", compresslevel=5))
            cur = self.files[symbol]
        line = f"{ts_ns:019d} {raw}\n"
        cur[1].write(line)
        self.bytes[symbol] += len(line)

    def flush(self) -> None:
        for _, f in self.files.values():
            f.flush()

    def close(self) -> None:
        for _, f in self.files.values():
            f.close()
        self.files.clear()


# ----------------------------------------------------------------------------- depth sequence

class DepthSequencer:
    """USD-M diff-depth continuity: each event's `pu` must equal the previous event's `u`."""

    def __init__(self):
        self.last_u: dict[str, int] = {}
        self.gaps = defaultdict(int)

    def check(self, symbol: str, data: dict) -> bool:
        """True if continuous (or first event); False means a gap was detected."""
        u, pu = data.get("u"), data.get("pu")
        prev = self.last_u.get(symbol)
        self.last_u[symbol] = u
        if prev is None or pu == prev:
            return True
        self.gaps[symbol] += 1
        return False

    def reset(self, symbol: str) -> None:
        self.last_u.pop(symbol, None)


# ----------------------------------------------------------------------------- collector

class Collector:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.writer = DailyGzipWriter(cfg.out_dir)
        self.seq = DepthSequencer()
        self.msgs = defaultdict(int)
        self.lat_ms = defaultdict(list)          # local receive - exchange event time, sampled
        self.reconnects = 0
        self.stop = asyncio.Event()
        self.snapshot_q: asyncio.Queue[str] = asyncio.Queue()

    # ---- REST snapshot (blocking urllib in a thread; public endpoint, no key)
    def _fetch_snapshot(self, symbol: str) -> str:
        url = f"{self.cfg.rest_url}/fapi/v1/depth?symbol={symbol}&limit={self.cfg.snapshot_limit}"
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read().decode()

    async def _snapshot_worker(self):
        while not self.stop.is_set():
            sym = await self.snapshot_q.get()
            try:
                raw = await asyncio.to_thread(self._fetch_snapshot, sym)
                ts = time.time_ns()
                json.loads(raw)                                 # validate
                self.writer.write(sym, ts, raw.replace("\n", ""))
                log.info("snapshot %s written", sym)
            except Exception as e:                              # noqa: BLE001
                log.warning("snapshot %s failed: %r; retry in 5s", sym, e)
                await asyncio.sleep(5)
                await self.snapshot_q.put(sym)
            await asyncio.sleep(0.25)                           # stay far below REST weight limits

    def _depth_symbols(self, group: list[str]) -> list[str]:
        return [s for s in group if any(st.startswith("depth") for st in self.cfg.symbols[s])]

    async def _periodic_snapshots(self):
        while not self.stop.is_set():
            await asyncio.sleep(self.cfg.snapshot_every_s)
            for s, st in self.cfg.symbols.items():
                if any(x.startswith("depth") for x in st):
                    await self.snapshot_q.put(s)

    async def _run_connection(self, group: list[str]):
        streams = [f"{s.lower()}@{st}" for s in group for st in self.cfg.symbols[s]]
        url = f"{self.cfg.ws_url}?streams={'/'.join(streams)}"
        backoff = 1.0
        while not self.stop.is_set():
            try:
                async with websockets.connect(url, max_size=2 ** 24, ping_interval=None,
                                              open_timeout=10) as ws:
                    log.info("connected: %d streams", len(streams))
                    backoff = 1.0
                    for s in self._depth_symbols(group):          # resync books after (re)connect
                        self.seq.reset(s)
                        await self.snapshot_q.put(s)
                    t_open = time.monotonic()
                    while not self.stop.is_set():
                        if time.monotonic() - t_open > self.cfg.reconnect_every_s:
                            log.info("scheduled reconnect")
                            break
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            log.warning("no data for 30s; reconnecting")
                            break
                        ts = time.time_ns()                       # stamp before parsing
                        self._handle(raw, ts)
            except Exception as e:                                # noqa: BLE001
                log.warning("connection error: %r", e)
            if self.stop.is_set():
                break
            self.reconnects += 1
            delay = min(backoff, 60) * (1 + random.random() * 0.2)
            log.info("reconnecting in %.1fs", delay)
            await asyncio.sleep(delay)
            backoff *= 2

    def _handle(self, raw: str | bytes, ts: int) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("bad json dropped")
            return
        stream, data = msg.get("stream", ""), msg.get("data") or {}
        sym = (data.get("s") or stream.split("@")[0]).upper()
        if sym not in self.cfg.symbols:
            return
        kind = stream.split("@", 1)[1] if "@" in stream else data.get("e", "?")
        self.msgs[f"{sym}@{kind}"] += 1
        if data.get("e") == "depthUpdate" and not self.seq.check(sym, data):
            log.warning("depth gap on %s (pu=%s); requesting snapshot", sym, data.get("pu"))
            self.seq.reset(sym)
            self.seq.check(sym, data)
            self.snapshot_q.put_nowait(sym)
        e_time = data.get("E")
        if e_time and len(self.lat_ms[sym]) < 5000:
            self.lat_ms[sym].append(ts / 1e6 - e_time)
        self.writer.write(sym, ts, raw if isinstance(raw, str) else raw.decode())

    async def _exchange_info(self):
        """Save /fapi/v1/exchangeInfo once per UTC day (tick size, lot size for hftbacktest)."""
        done = None
        while not self.stop.is_set():
            day = time.strftime("%Y%m%d", time.gmtime())
            if day != done:
                try:
                    url = f"{self.cfg.rest_url}/fapi/v1/exchangeInfo"
                    raw = await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=10).read())
                    p = Path(self.cfg.out_dir) / day / "exchangeInfo.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(raw)
                    done = day
                    log.info("exchangeInfo saved for %s", day)
                except Exception as e:                              # noqa: BLE001
                    log.warning("exchangeInfo failed: %r", e)
            await asyncio.sleep(600)

    async def _flusher(self):
        while not self.stop.is_set():
            await asyncio.sleep(self.cfg.flush_every_s)
            self.writer.flush()

    async def _stats(self):
        while not self.stop.is_set():
            await asyncio.sleep(self.cfg.stats_every_s)
            dt = self.cfg.stats_every_s
            rates = {k: round(v / dt, 1) for k, v in sorted(self.msgs.items())}
            lat = {s: round(sorted(v)[len(v) // 2], 1) for s, v in self.lat_ms.items() if v}
            log.info("msg/s %s | median recv-E latency ms %s | gaps %s | reconnects %d | MB written %s",
                     rates, lat, dict(self.seq.gaps), self.reconnects,
                     {s: round(b / 1e6, 1) for s, b in self.writer.bytes.items()})
            self.msgs.clear()
            self.lat_ms.clear()

    async def run(self):
        syms = list(self.cfg.symbols)
        groups, cur, n = [], [], 0
        for s in syms:
            k = len(self.cfg.symbols[s])
            if n + k > self.cfg.max_streams_per_conn and cur:
                groups.append(cur); cur, n = [], 0
            cur.append(s); n += k
        if cur:
            groups.append(cur)
        tasks = [asyncio.create_task(self._run_connection(g)) for g in groups]
        tasks += [asyncio.create_task(x) for x in (self._snapshot_worker(), self._flusher(),
                                                   self._stats(), self._periodic_snapshots(),
                                                   self._exchange_info())]
        await self.stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.writer.close()
        log.info("stopped")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--log-level", default="INFO")
    a = ap.parse_args(argv)
    logging.basicConfig(level=a.log_level, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.load(a.config)
    if a.out:
        cfg.out_dir = a.out
    c = Collector(cfg)
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, c.stop.set)
        except NotImplementedError:
            pass
    loop.run_until_complete(c.run())


if __name__ == "__main__":
    main()
