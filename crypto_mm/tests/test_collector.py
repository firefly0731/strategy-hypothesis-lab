"""Integration test against a fake Binance (websocket + REST) running on localhost."""
import asyncio
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import websockets

from crypto_mm.collector import Collector, Config, DepthSequencer

SNAP = {"lastUpdateId": 99, "E": 1, "T": 1700000000000,
        "bids": [["100.0", "1.0"], ["99.9", "2.0"]], "asks": [["100.1", "1.5"], ["100.2", "3.0"]]}


def depth(U, u, pu, t):
    return {"stream": "btcusdc@depth@0ms", "data": {"e": "depthUpdate", "E": t + 1, "T": t, "s": "BTCUSDC",
            "U": U, "u": u, "pu": pu, "b": [["100.0", "1.2"]], "a": [["100.1", "0.0"], ["100.3", "1.0"]]}}


def trade(i, t, m):
    return {"stream": "btcusdc@trade", "data": {"e": "trade", "E": t + 1, "T": t, "s": "BTCUSDC", "t": i,
            "p": "100.05", "q": "0.01", "X": "MARKET", "m": m}}


def ticker(t):
    return {"stream": "btcusdc@bookTicker", "data": {"e": "bookTicker", "u": 5, "s": "BTCUSDC", "b": "100.0",
            "B": "1.2", "a": "100.3", "A": "1.0", "T": t, "E": t + 1}}


MSGS = [depth(100, 101, 99, 1700000000100), trade(1, 1700000000110, True),
        depth(102, 103, 101, 1700000000120), ticker(1700000000125),
        depth(110, 111, 105, 1700000000130),          # gap: pu != previous u
        trade(2, 1700000000140, False), depth(112, 113, 111, 1700000000150)]


class Rest(BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self):
        Rest.calls += 1
        if "exchangeInfo" in self.path:
            body = json.dumps({"symbols": [{"symbol": "BTCUSDC", "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.1"}, {"filterType": "LOT_SIZE", "stepSize": "0.001"}]}]}).encode()
        else:
            body = json.dumps(SNAP).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_sequencer():
    s = DepthSequencer()
    assert s.check("X", {"u": 1, "pu": 0})
    assert s.check("X", {"u": 2, "pu": 1})
    assert not s.check("X", {"u": 9, "pu": 5}) and s.gaps["X"] == 1


def test_collector_end_to_end(tmp_path):
    httpd = HTTPServer(("127.0.0.1", 0), Rest)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    conns = {"n": 0}

    async def handler(ws):
        conns["n"] += 1
        if conns["n"] == 1:
            for m in MSGS:
                await ws.send(json.dumps(m))
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.2)
            await ws.close()                           # force a reconnect
        else:
            await ws.send(json.dumps(trade(3, 1700000000200, True)))
            await asyncio.sleep(5)

    async def main():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            cfg = Config(out_dir=str(tmp_path), ws_url=f"ws://127.0.0.1:{port}/stream",
                         rest_url=f"http://127.0.0.1:{httpd.server_port}",
                         symbols={"BTCUSDC": ["depth@0ms", "trade", "bookTicker"]},
                         flush_every_s=0.05, stats_every_s=1, snapshot_every_s=3600)
            c = Collector(cfg)
            task = asyncio.create_task(c.run())
            await asyncio.sleep(4.0)
            c.stop.set()
            await task
            return c

    c = asyncio.run(main())
    httpd.shutdown()
    files = list(tmp_path.rglob("btcusdc.gz"))
    assert len(files) == 1
    lines = gzip.open(files[0], "rt").read().splitlines()
    assert all(len(l.split(" ", 1)[0]) == 19 and l.split(" ", 1)[0].isdigit() for l in lines)
    assert list(tmp_path.rglob("exchangeInfo.json"))
    from crypto_mm.convert_day import tick_lot
    assert tick_lot(next(tmp_path.rglob("exchangeInfo.json")), "btcusdc") == (0.1, 0.001)
    snaps = [l for l in lines if '"lastUpdateId"' in l]
    assert len(snaps) >= 3                       # initial + gap resync + after reconnect
    assert c.seq.gaps["BTCUSDC"] == 1 and c.reconnects >= 1
    assert sum('"e": "trade"' in l or '"e":"trade"' in l for l in lines) == 3

    # the file must be readable by hftbacktest's Binance Futures converter
    from hftbacktest.data.utils import binancefutures
    ev = binancefutures.convert(str(files[0]), opt="t", buffer_size=10_000)
    assert len(ev) > 0
    from hftbacktest.types import TRADE_EVENT, DEPTH_SNAPSHOT_EVENT
    kinds = ev["ev"] & 0xFF
    assert (kinds == TRADE_EVENT).sum() == 3
    assert (kinds == DEPTH_SNAPSHOT_EVENT).sum() >= 4 * 3   # 4 levels per snapshot


def test_prune_raw(tmp_path):
    from crypto_mm.collector import prune_raw, Config
    raw, npz = tmp_path / "raw", tmp_path / "npz"
    for day in ("20261101", "20261110", "20261118"):
        (raw / day).mkdir(parents=True)
        (raw / day / "ethusdc.gz").write_bytes(b"x")
        (raw / day / "solusdc.gz").write_bytes(b"x")
    npz.mkdir()
    (npz / "ethusdc_20261101.npz").write_bytes(b"x")          # 20261101 only half converted
    for s in ("ethusdc", "solusdc"):
        (npz / f"{s}_20261110.npz").write_bytes(b"x")         # 20261110 fully converted
    assert prune_raw(str(raw), 0) == []                         # disabled
    # 7-day retention: 1101 and 1110 are old enough, but only 1110 is fully converted
    assert prune_raw(str(raw), 7, str(npz), today="20261119") == ["20261110"]
    assert (raw / "20261101").exists() and (raw / "20261118").exists()
    # without the conversion guard both old days go
    assert prune_raw(str(raw), 7, "", today="20261119") == ["20261101"]
    c = Config.load("crypto_mm/collector.toml")
    assert set(c.symbols) == {"ETHUSDC", "SOLUSDC", "XRPUSDC", "ETHUSDT", "SOLUSDT", "XRPUSDT"}
    assert c.retention_days == 7 and c.converted_dir == "./md_npz"


def test_market_streams_routed_to_market_endpoint():
    from crypto_mm.collector import is_market_stream
    assert is_market_stream("aggTrade") and is_market_stream("kline_1m")
    assert not is_market_stream("bookTicker") and not is_market_stream("depth@100ms")
    assert not is_market_stream("trade")


def test_scheduled_rotation_is_make_before_break(tmp_path):
    """A fake exchange broadcasts one continuous event sequence to every open connection. Scheduled
    rotations must leave no hole, no duplicate and no depth gap, and must not trigger a resync."""
    httpd = HTTPServer(("127.0.0.1", 0), Rest)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    clients: set[asyncio.Queue] = set()
    conns = {"n": 0}

    async def exchange(stop):
        i = 0
        while not stop.is_set():
            i += 1
            t = 1700000000000 + i
            for m in (depth(100 + 2 * i, 101 + 2 * i, 99 + 2 * i, t), trade(i, t, i % 2 == 0)):
                for q in list(clients):
                    q.put_nowait(json.dumps(m))
            await asyncio.sleep(0.005)

    async def handler(ws):
        conns["n"] += 1
        q = asyncio.Queue()
        clients.add(q)
        try:
            while (m := await q.get()) is not None:      # None: the test is shutting down
                await ws.send(m)
        except websockets.ConnectionClosed:
            pass
        finally:
            clients.discard(q)

    async def main():
        stop = asyncio.Event()
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            prod = asyncio.create_task(exchange(stop))
            cfg = Config(out_dir=str(tmp_path), ws_url=f"ws://127.0.0.1:{port}/stream",
                         rest_url=f"http://127.0.0.1:{httpd.server_port}",
                         symbols={"BTCUSDC": ["depth@0ms", "trade"]},
                         flush_every_s=0.05, stats_every_s=1, snapshot_every_s=3600,
                         reconnect_every_s=1, handover_overlap_s=0.3)
            c = Collector(cfg)
            task = asyncio.create_task(c.run())
            await asyncio.sleep(4.0)
            c.stop.set()
            await task
            stop.set()
            await prod
            for q in list(clients):
                q.put_nowait(None)
            return c

    c = asyncio.run(main())
    httpd.shutdown()
    assert c.handovers >= 2 and c.reconnects == 0 and conns["n"] == c.handovers + 1
    assert c.dupes > 0 and not c.seq.gaps
    lines = gzip.open(next(tmp_path.rglob("btcusdc.gz")), "rt").read().splitlines()
    stamps = [int(l.split(" ", 1)[0]) for l in lines]
    assert stamps == sorted(stamps)
    recs = [json.loads(l.split(" ", 1)[1]) for l in lines]
    assert sum("lastUpdateId" in r for r in recs) == 1          # only the initial snapshot
    us = [r["data"]["u"] for r in recs if r.get("data", {}).get("e") == "depthUpdate"]
    ts = [r["data"]["t"] for r in recs if r.get("data", {}).get("e") == "trade"]
    assert us == list(range(us[0], us[0] + 2 * len(us), 2))      # contiguous, no duplicates
    assert ts == list(range(ts[0], ts[0] + len(ts)))
