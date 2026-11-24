"""Daily compaction of the order-book collector's raw gzip files into parquet (stage OB).

    python -m mm_tick.ob_compact --raw C:/Users/smile-user/md_local/ob_raw --out C:/Users/smile-user/md_local/ob_pq
    python -m mm_tick.ob_compact ... --delete-raw      # delete a day's raw .gz only after verification

Only UTC days before today are processed (the collector may still be writing today). Per symbol:
  <out>/<day>/<sym>_bbo.parquet    bookTicker   T, lat_ms, bid_k, spr_k (ticks), bid_qty, ask_qty, tick
  <out>/<day>/<sym>_trade.parquet  aggTrade     local_ns, E, T, a, px, qty, buyer_maker
  <out>/<day>/<sym>_depth.parquet  diff depth   local_ns, E, T, U, u, pu, side (+1 bid, -1 ask), px, qty
  <out>/<day>/<sym>_snap.parquet   REST depth   local_ns, last_id, side, px, qty
Verification: every line parsed, and each parquet re-read has the row count written. A raw file is
deleted only when --delete-raw is given, the gzip read to its end without error, and every
parquet of that file verified (user decision 2026-11-25: delete raw only after a verified
conversion). A raw file that fails is kept and reported.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("mm_tick.ob_compact")


def infer_tick(px: np.ndarray) -> float:
    """Smallest positive step between distinct prices, if every price sits on that grid; else 0."""
    u = np.unique(px)
    if len(u) < 2:
        return 0.0
    tick = float(np.min(np.diff(u)))
    k = px / tick
    return tick if np.max(np.abs(k - np.rint(k))) < 1e-3 else 0.0


def compact_bbo(x: pd.DataFrame) -> pd.DataFrame:
    """Prices in integer ticks (tick in its own column), quantities float32, local receive time as
    a latency in ms against the transaction time T; E and u dropped. Falls back to float64
    prices when the tick cannot be inferred (tick = 0)."""
    tick = infer_tick(np.r_[x["bid"].to_numpy(), x["ask"].to_numpy()])
    y = pd.DataFrame({"T": x["T"].astype(np.int64),
                      "lat_ms": ((x["local_ns"] // 1_000_000) - x["T"]).astype(np.int32)})
    if tick > 0:
        y["bid_k"] = np.rint(x["bid"].to_numpy() / tick).astype(np.int64)
        y["spr_k"] = np.rint((x["ask"].to_numpy() - x["bid"].to_numpy()) / tick).astype(np.int32)
    else:
        y["bid"], y["ask"] = x["bid"], x["ask"]
    y["bid_qty"] = x["bid_qty"].astype(np.float32)
    y["ask_qty"] = x["ask_qty"].astype(np.float32)
    y["tick"] = tick
    return y


def parse_file(path: Path):
    """Returns ({kind: DataFrame}, n_lines, n_unparsed). Raises on a truncated gzip."""
    bbo, trd, dep, snap = [], [], [], []
    n = bad = 0
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
                    lid = m["lastUpdateId"]
                    for sd, key in ((1, "bids"), (-1, "asks")):
                        for p, q in m[key]:
                            snap.append((ns, lid, sd, float(p), float(q)))
                else:
                    bad += 1
                continue
            d = m["data"]
            if st.endswith("@bookTicker"):
                bbo.append((ns, d["E"], d["T"], d["u"], float(d["b"]), float(d["B"]), float(d["a"]), float(d["A"])))
            elif st.endswith("@aggTrade"):
                trd.append((ns, d["E"], d["T"], d["a"], float(d["p"]), float(d["q"]), bool(d["m"])))
            elif "@depth" in st:
                for sd, key in ((1, "b"), (-1, "a")):
                    for p, q in d[key]:
                        dep.append((ns, d["E"], d["T"], d["U"], d["u"], d["pu"], sd, float(p), float(q)))
            else:
                bad += 1
    out = {}
    if bbo:
        out["bbo"] = compact_bbo(pd.DataFrame(bbo, columns=["local_ns", "E", "T", "u", "bid", "bid_qty", "ask",
                                                            "ask_qty"]))
    if trd:
        out["trade"] = pd.DataFrame(trd, columns=["local_ns", "E", "T", "a", "px", "qty", "buyer_maker"])
    if dep:
        x = pd.DataFrame(dep, columns=["local_ns", "E", "T", "U", "u", "pu", "side", "px", "qty"])
        x["side"] = x["side"].astype(np.int8)
        out["depth"] = x
    if snap:
        x = pd.DataFrame(snap, columns=["local_ns", "last_id", "side", "px", "qty"])
        x["side"] = x["side"].astype(np.int8)
        out["snap"] = x
    return out, n, bad


def compact_day(day_dir: Path, out_root: Path, delete_raw: bool) -> list[dict]:
    rep = []
    od = out_root / day_dir.name
    od.mkdir(parents=True, exist_ok=True)
    for gz in sorted(day_dir.glob("*.gz")):
        sym = gz.stem
        r = {"day": day_dir.name, "sym": sym, "raw_mb": gz.stat().st_size / 1e6, "ok": False, "deleted": False}
        try:
            frames, n, bad = parse_file(gz)
        except (EOFError, OSError) as e:          # truncated or corrupt gzip: keep the raw file
            r["error"] = f"read: {e}"
            rep.append(r)
            continue
        r.update(lines=n, unparsed=bad)
        ok = bad == 0
        for kind, x in frames.items():
            p = od / f"{sym}_{kind}.parquet"
            x.to_parquet(p, compression="zstd", compression_level=19)
            back = pd.read_parquet(p, columns=[x.columns[0]])
            r[f"n_{kind}"] = len(x)
            ok &= len(back) == len(x)
        r["pq_mb"] = sum((od / f"{sym}_{k}.parquet").stat().st_size for k in frames) / 1e6
        r["ok"] = bool(ok and frames)
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
