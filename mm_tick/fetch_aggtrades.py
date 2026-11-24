"""Download Binance USD-M monthly aggTrades and store them as compact parquet.

    python -m mm_tick.fetch_aggtrades --symbols BTCUSDT ETHUSDT SOLUSDT --months 2026-05 2026-10

Per month: download the zip and its .CHECKSUM into <out>/<SYM>/, verify SHA-256, stream the CSV
into <out>/<SYM>/<YYYY-MM>.parquet (zstd), check the row count, then remove the zip this script
downloaded. Existing parquet files are skipped. Stops before a download when free disk would fall
below --min-free-gb. Never touches any other file.

Columns kept: t (exchange transact time, ms, int64), px (float64), qty (float64),
buyer_maker (bool; True = the aggressor sold).
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

BASE = "https://data.binance.vision/data/futures/um/monthly/aggTrades"
OUT = Path("C:/Users/smile-user/md_local/aggtrades")
NAMES = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
         "transact_time", "is_buyer_maker"]
log = logging.getLogger("fetch_aggtrades")


def months_between(a: str, b: str) -> list[str]:
    y, m = map(int, a.split("-"))
    y2, m2 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _get(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def convert(zpath: Path, dest: Path) -> int:
    """Stream the CSV inside `zpath` to parquet; return the row count."""
    with zipfile.ZipFile(zpath) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            has_header = not f.readline()[:1].isdigit()
        with z.open(name) as f:
            ro = pacsv.ReadOptions(block_size=64 << 20, skip_rows=1 if has_header else 0,
                                   column_names=NAMES)
            co = pacsv.ConvertOptions(
                include_columns=["transact_time", "price", "quantity", "is_buyer_maker"],
                column_types={"transact_time": pa.int64(), "price": pa.float64(),
                              "quantity": pa.float64(), "is_buyer_maker": pa.bool_()})
            reader = pacsv.open_csv(f, read_options=ro, convert_options=co)
            schema = pa.schema([("t", pa.int64()), ("px", pa.float64()), ("qty", pa.float64()),
                                ("buyer_maker", pa.bool_())])
            tmp = dest.with_suffix(".parquet.part")
            n = 0
            with pq.ParquetWriter(tmp, schema, compression="zstd", compression_level=6) as w:
                for b in reader:
                    t = pa.table([b.column("transact_time"), b.column("price"),
                                  b.column("quantity"), b.column("is_buyer_maker")], schema=schema)
                    w.write_table(t)
                    n += t.num_rows
    if pq.ParquetFile(tmp).metadata.num_rows != n:
        raise RuntimeError(f"row count mismatch in {tmp}")
    tmp.replace(dest)
    return n


def fetch(sym: str, month: str, out: Path, min_free_gb: float) -> str:
    d = out / sym
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{month}.parquet"
    if dest.exists():
        return "exists"
    free = shutil.disk_usage(d).free / 1e9
    if free < min_free_gb:
        raise SystemExit(f"stop: {free:.1f} GB free < {min_free_gb} GB")
    fn = f"{sym}-aggTrades-{month}.zip"
    zpath, cpath = d / fn, d / (fn + ".CHECKSUM")
    try:
        _get(f"{BASE}/{sym}/{fn}.CHECKSUM", cpath)
    except urllib.error.HTTPError as e:
        if e.code == 404:                   # not listed (yet) in that month
            cpath.unlink(missing_ok=True)
            return "not listed"
        raise
    _get(f"{BASE}/{sym}/{fn}", zpath)
    want = cpath.read_text().split()[0]
    if _sha256(zpath) != want:
        raise RuntimeError(f"checksum mismatch: {zpath}")
    n = convert(zpath, dest)
    zpath.unlink()           # the zip this run downloaded; the parquet is verified above
    cpath.unlink()
    return f"{n:,} rows, {dest.stat().st_size / 1e6:.0f} MB"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--months", nargs=2, required=True, metavar=("FIRST", "LAST"))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--min-free-gb", type=float, default=15.0)
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
    for m in months_between(*a.months):
        for s in a.symbols:
            log.info("%s %s: %s", s, m, fetch(s, m, a.out, a.min_free_gb))


if __name__ == "__main__":
    main()
