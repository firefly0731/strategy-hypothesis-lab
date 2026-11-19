"""Convert one collected UTC day to hftbacktest .npz files and report feed quality.

    python -m crypto_mm.convert_day --raw ./md_raw --day 20261120 --out ./md_npz

For every <symbol>.gz it writes <out>/<symbol>_<day>.npz (bookTicker included via opt="t")
and prints: events, trades, snapshots, feed latency (local - exchange) p50/p90/p99 in ms.
Tick / lot size come from <raw>/<day>/exchangeInfo.json (saved by the collector), for later use
with hftbacktest's BacktestAsset and create_last_snapshot.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from hftbacktest.data.utils import binancefutures
from hftbacktest.types import DEPTH_EVENT, DEPTH_SNAPSHOT_EVENT, TRADE_EVENT


def tick_lot(info_path: Path, symbol: str):
    if not info_path.exists():
        return None, None
    info = json.loads(info_path.read_text())
    for s in info.get("symbols", []):
        if s["symbol"] == symbol.upper():
            f = {x["filterType"]: x for x in s["filters"]}
            return float(f["PRICE_FILTER"]["tickSize"]), float(f["LOT_SIZE"]["stepSize"])
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--day", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    src = Path(a.raw) / a.day
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for gz in sorted(src.glob("*.gz")):
        sym = gz.stem
        ev = binancefutures.convert(str(gz), output_filename=str(out / f"{sym}_{a.day}.npz"), opt="t")
        k = ev["ev"] & 0xFF
        lat = (ev["local_ts"] - ev["exch_ts"]) / 1e6
        lat = lat[(k == DEPTH_EVENT) | (k == TRADE_EVENT)]
        tick, lot = tick_lot(src / "exchangeInfo.json", sym)
        p = np.percentile(lat, [50, 90, 99]) if len(lat) else [np.nan] * 3
        print(f"{sym}: events={len(ev):,} depth={(k == DEPTH_EVENT).sum():,} trades={(k == TRADE_EVENT).sum():,} "
              f"snapshot_rows={(k == DEPTH_SNAPSHOT_EVENT).sum():,} feed latency ms p50/p90/p99="
              f"{p[0]:.1f}/{p[1]:.1f}/{p[2]:.1f} tick={tick} lot={lot}")


if __name__ == "__main__":
    main()
