"""Daily compaction of the order-book collector's raw gzip files into parquet (stage OB).

    python -m mm_tick.ob_compact --raw /Users/yjban/MarketData/ob_raw --out /Users/yjban/MarketData/ob_pq
    python -m mm_tick.ob_compact ... --delete-raw      # delete a raw .gz only after verification

Only UTC days before today are processed (the collector may still be writing today). Prices are
stored as integer ticks (`px_k`, `bid_k`; price = k x tick, the tick in its own column), quantities
as float32, the local receive time as a latency in ms against the event's transaction time T.
Per symbol and day, <out>/<day>/<sym>_<kind>.parquet:
  bbo       bookTicker      T, lat_ms, bid_k, spr_k, bid_qty, ask_qty, tick
  trade     aggTrade        T, lat_ms, a, px_k, qty, buyer_maker, tick
  depth_ev  diff depth      ev, T, lat_ms, dE (E - T), U, u, pu        (one row per message)
  depth_lv  diff depth      ev, side (+1 bid, -1 ask), px_k, qty, tick  (one row per level; qty 0 = removed)
  snap_ev   REST depth      ev, local_ms, last_id
  snap_lv   REST depth      ev, side, px_k, qty, tick
  liq       forceOrder      T, lat_ms, E, side (+1 buy, -1 sell), px, avg_px, qty, last_qty, cum_qty, status, otype
  mark      markPrice       E, lat_ms, mark, index, est_settle, funding, next_funding_T
The tick comes from the day's exchangeInfo.json (written by the collector), else from the prices;
every price must sit on that grid. Verification: every line parsed, every price on the grid, and
each parquet's row count (from its footer) equal to the rows written. A raw file is deleted only
with --delete-raw, after the gzip was read to its end and every parquet of it verified (user
decision 2026-11-25: delete raw only after a verified conversion). A failing raw file is kept.
Files are written in row groups, so a day of BTC diff depth does not have to fit in memory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import logging
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger("mm_tick.ob_compact")
CHUNK = 2_000_000            # rows per kind held in memory before a row group is written
ZSTD = 19


class OffGrid(ValueError):
    pass


def infer_tick(px: np.ndarray) -> float:
    """Smallest positive step between distinct prices, if every price sits on that grid; else 0."""
    u = np.unique(px)
    if len(u) < 2:
        return 0.0
    tick = float(np.min(np.diff(u)))
    k = px / tick
    return tick if np.max(np.abs(k - np.rint(k))) < 1e-3 else 0.0


def to_ticks(px: np.ndarray, tick: float) -> np.ndarray:
    k = px / tick
    r = np.rint(k)
    if len(k) and np.max(np.abs(k - r)) > 1e-6 * np.maximum(1.0, np.max(np.abs(r))) + 1e-6:
        raise OffGrid(f"price off the {tick} grid")
    return r.astype(np.int64)


def compact_bbo(x: pd.DataFrame, tick: float | None = None) -> pd.DataFrame:
    """Prices in integer ticks, quantities float32, receive time as latency in ms against T."""
    if tick is None:
        tick = infer_tick(np.r_[x["bid"].to_numpy(), x["ask"].to_numpy()])
    y = pd.DataFrame({"T": x["T"].astype(np.int64),
                      "lat_ms": ((x["local_ns"] // 1_000_000) - x["T"]).astype(np.int32)})
    if tick > 0:
        b = to_ticks(x["bid"].to_numpy(), tick)
        y["bid_k"] = b
        y["spr_k"] = (to_ticks(x["ask"].to_numpy(), tick) - b).astype(np.int32)
    else:
        y["bid"], y["ask"] = x["bid"], x["ask"]
    y["bid_qty"] = x["bid_qty"].astype(np.float32)
    y["ask_qty"] = x["ask_qty"].astype(np.float32)
    y["tick"] = tick
    return y


def day_ticks(day_dir: Path) -> dict[str, float]:
    p = day_dir / "exchangeInfo.json"
    if not p.exists():
        return {}
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for s in info.get("symbols", []):
        for f in s.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                out[s["symbol"].lower()] = float(f["tickSize"])
    return out


class Sink:
    """Buffered parquet writer for one kind; `conv` turns a list of tuples into a DataFrame."""

    def __init__(self, path: Path, conv):
        self.path, self.conv = path, conv
        self.rows: list = []
        self.writer = None
        self.n = 0

    def add(self, row):
        self.rows.append(row)
        if len(self.rows) >= CHUNK:
            self.flush()

    def flush(self):
        if not self.rows:
            return
        t = pa.Table.from_pandas(self.conv(self.rows), preserve_index=False)
        if self.writer is None:
            # integer columns (times, ids, ticks) delta-encoded: about 20% smaller than dictionary + zstd
            ints = [f.name for f in t.schema if pa.types.is_integer(f.type)]
            other = [f.name for f in t.schema if f.name not in ints]
            self.writer = pq.ParquetWriter(self.path, t.schema, compression="zstd", compression_level=ZSTD,
                                           use_dictionary=other, column_encoding={c: "DELTA_BINARY_PACKED" for c in ints})
        self.writer.write_table(t)
        self.n += t.num_rows
        self.rows = []

    def close(self) -> int:
        self.flush()
        if self.writer is not None:
            self.writer.close()
        return self.n


def _lat(local_ns, T):
    return (np.asarray(local_ns, dtype=np.int64) // 1_000_000 - np.asarray(T, dtype=np.int64)).astype(np.int32)


def make_convs(tick_ref: list):
    """Converters; tick_ref[0] is the tick (set from exchangeInfo, or from the first prices seen)."""

    def tick_for(px):
        if tick_ref[0] <= 0:
            tick_ref[0] = infer_tick(np.asarray(px, dtype=np.float64))
            if tick_ref[0] <= 0:
                raise OffGrid("tick cannot be inferred")
        return tick_ref[0]

    def bbo(rows):
        x = pd.DataFrame(rows, columns=["local_ns", "E", "T", "u", "bid", "bid_qty", "ask", "ask_qty"])
        return compact_bbo(x, tick_for(np.r_[x["bid"].to_numpy(), x["ask"].to_numpy()]))

    def trade(rows):
        x = pd.DataFrame(rows, columns=["local_ns", "E", "T", "a", "px", "qty", "buyer_maker"])
        tk = tick_for(x["px"].to_numpy())
        return pd.DataFrame({"T": x["T"].astype(np.int64), "lat_ms": _lat(x["local_ns"], x["T"]),
                             "a": x["a"].astype(np.int64), "px_k": to_ticks(x["px"].to_numpy(), tk),
                             "qty": x["qty"].astype(np.float32), "buyer_maker": x["buyer_maker"].astype(bool),
                             "tick": tk})

    def depth_ev(rows):
        x = pd.DataFrame(rows, columns=["ev", "local_ns", "E", "T", "U", "u", "pu"])
        return pd.DataFrame({"ev": x["ev"].astype(np.int64), "T": x["T"].astype(np.int64),
                             "lat_ms": _lat(x["local_ns"], x["T"]), "dE": (x["E"] - x["T"]).astype(np.int32),
                             "U": x["U"].astype(np.int64), "u": x["u"].astype(np.int64), "pu": x["pu"].astype(np.int64)})

    def levels(rows):
        x = pd.DataFrame(rows, columns=["ev", "side", "px", "qty"])
        tk = tick_for(x["px"].to_numpy())
        return pd.DataFrame({"ev": x["ev"].astype(np.int64), "side": x["side"].astype(np.int8),
                             "px_k": to_ticks(x["px"].to_numpy(), tk), "qty": x["qty"].astype(np.float32),
                             "tick": tk})

    def snap_ev(rows):
        x = pd.DataFrame(rows, columns=["ev", "local_ns", "last_id"])
        return pd.DataFrame({"ev": x["ev"].astype(np.int64), "local_ms": (x["local_ns"] // 1_000_000).astype(np.int64),
                             "last_id": x["last_id"].astype(np.int64)})

    def liq(rows):
        x = pd.DataFrame(rows, columns=["local_ns", "E", "T", "side", "px", "avg_px", "qty", "last_qty", "cum_qty",
                                        "status", "otype"])
        x["lat_ms"] = _lat(x["local_ns"], x["T"])
        x["side"] = x["side"].astype(np.int8)
        return x.drop(columns="local_ns")

    def mark(rows):
        x = pd.DataFrame(rows, columns=["local_ns", "E", "mark", "index", "est_settle", "funding", "next_funding_T"])
        x["lat_ms"] = _lat(x["local_ns"], x["E"])
        x["funding"] = x["funding"].astype(np.float32)
        return x.drop(columns="local_ns")

    return {"bbo": bbo, "trade": trade, "depth_ev": depth_ev, "depth_lv": levels, "snap_ev": snap_ev,
            "snap_lv": levels, "liq": liq, "mark": mark}


def parse_file(path: Path, od: Path, sym: str, tick: float = 0.0):
    """Streams one raw file into parquet sinks. Returns ({kind: rows written}, n_lines, n_unparsed).
    Raises on a truncated or corrupt gzip, and OffGrid if a price is off the tick grid."""
    tick_ref = [tick]
    conv = make_convs(tick_ref)
    sinks = {k: Sink(od / f"{sym}_{k}.parquet", c) for k, c in conv.items()}
    n = bad = 0
    dev = sev = 0
    try:
        with gzip.open(path, "rt") as f:
            for line in f:
                n += 1
                ts, _, raw = line.partition(" ")
                try:
                    ns = int(ts)
                    m = json.loads(raw)
                except ValueError:
                    bad += 1
                    continue
                st = m.get("stream")
                if st is None:
                    if "lastUpdateId" in m:
                        sinks["snap_ev"].add((sev, ns, m["lastUpdateId"]))
                        for sd, key in ((1, "bids"), (-1, "asks")):
                            for p, q in m[key]:
                                sinks["snap_lv"].add((sev, sd, float(p), float(q)))
                        sev += 1
                    else:
                        bad += 1
                    continue
                d = m.get("data") or {}
                if st.endswith("@bookTicker"):
                    sinks["bbo"].add((ns, d["E"], d["T"], d["u"], float(d["b"]), float(d["B"]), float(d["a"]),
                                      float(d["A"])))
                elif st.endswith("@aggTrade"):
                    sinks["trade"].add((ns, d["E"], d["T"], d["a"], float(d["p"]), float(d["q"]), bool(d["m"])))
                elif "@depth" in st:
                    sinks["depth_ev"].add((dev, ns, d["E"], d["T"], d["U"], d["u"], d["pu"]))
                    for sd, key in ((1, "b"), (-1, "a")):
                        for p, q in d[key]:
                            sinks["depth_lv"].add((dev, sd, float(p), float(q)))
                    dev += 1
                elif st.endswith("@forceOrder"):
                    o = d["o"]
                    sinks["liq"].add((ns, d["E"], o["T"], 1 if o["S"] == "BUY" else -1, float(o["p"]), float(o["ap"]),
                                      float(o["q"]), float(o["l"]), float(o["z"]), o["X"], o["o"]))
                elif "@markPrice" in st:
                    sinks["mark"].add((ns, d["E"], float(d["p"]), float(d["i"]), float(d["P"]), float(d["r"]),
                                       int(d["T"])))
                else:
                    bad += 1
    finally:
        written = {}
        err = None
        for k, s in sinks.items():
            try:
                written[k] = s.close()
            except OffGrid as e:          # a late chunk off the grid: report after closing the others
                err = e
                written[k] = -1
        for k, s in sinks.items():
            if s.writer is None and s.path.exists() and written.get(k, 0) == 0:
                s.path.unlink()
    if err is not None:
        raise err
    return {k: v for k, v in written.items() if v > 0}, n, bad


def compact_day(day_dir: Path, out_root: Path, delete_raw: bool) -> list[dict]:
    rep = []
    od = out_root / day_dir.name
    od.mkdir(parents=True, exist_ok=True)
    ticks = day_ticks(day_dir)
    for gz in sorted(day_dir.glob("*.gz")):
        sym = gz.stem
        r = {"day": day_dir.name, "sym": sym, "raw_mb": gz.stat().st_size / 1e6, "ok": False, "deleted": False}
        try:
            written, n, bad = parse_file(gz, od, sym, ticks.get(sym, 0.0))
        except (EOFError, OSError, zlib.error) as e:      # truncated or corrupt gzip: keep the raw file
            r["error"] = f"read: {e}"
            rep.append(r)
            continue
        except (OffGrid, KeyError, TypeError) as e:
            r["error"] = f"parse: {e!r}"
            rep.append(r)
            continue
        r.update(lines=n, unparsed=bad)
        ok = bad == 0 and bool(written)
        for kind, cnt in written.items():
            p = od / f"{sym}_{kind}.parquet"
            r[f"n_{kind}"] = cnt
            ok &= pq.ParquetFile(p).metadata.num_rows == cnt
        r["pq_mb"] = sum((od / f"{sym}_{k}.parquet").stat().st_size for k in written) / 1e6
        r["ok"] = bool(ok)
        if delete_raw and r["ok"]:
            gz.unlink()
            r["deleted"] = True
        rep.append(r)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--delete-raw", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = []
    for day_dir in sorted(p for p in raw.iterdir() if p.is_dir() and p.name.isdigit() and p.name < today):
        if not any(day_dir.glob("*.gz")):
            continue
        rep += compact_day(day_dir, out, a.delete_raw)
    if rep:
        df = pd.DataFrame(rep)
        log.info("\n%s", df.to_string(index=False))
        p = out / "compact_report.csv"
        df.to_csv(p, mode="a", header=not p.exists(), index=False)
        if not df["ok"].all():
            log.error("kept raw files that failed verification: %s", df.loc[~df["ok"], ["day", "sym"]].values.tolist())
    else:
        log.info("nothing to compact")


if __name__ == "__main__":
    main()
