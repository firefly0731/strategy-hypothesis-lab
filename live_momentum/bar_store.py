"""Closed 1m bars collected live, persisted per UTC day, merged with the public archive.

The research archive (data.binance.vision) is published with a delay of about a day, so the
history used at the open = archive + bars collected live (or fetched by REST) after it.
"""
from __future__ import annotations

import logging

from pathlib import Path

import pandas as pd

from .bars import PRICE, VOLS, regularize

COLS = list(PRICE) + list(VOLS)


class BarStore:
    def __init__(self, root: Path, symbol: str):
        self.root = Path(root) / "bars" / symbol
        self.symbol = symbol
        self.rows: dict[pd.Timestamp, dict] = {}
        self._dirty_days: set = set()

    # ---------------------------------------------------------------- collect
    def add(self, open_time: pd.Timestamp, row: dict) -> None:
        self.rows[open_time] = {c: row[c] for c in COLS}
        self._dirty_days.add(open_time.normalize())

    def add_frame(self, df: pd.DataFrame) -> None:
        for t, r in df[COLS].iterrows():
            self.add(t, r.to_dict())

    def has(self, open_time: pd.Timestamp) -> bool:
        return open_time in self.rows

    def missing(self, start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
        """Bar open_times in [start, end) not collected."""
        return [t for t in pd.date_range(start, end, freq="1min", inclusive="left", tz="UTC")
                if t not in self.rows]

    def frame(self, start: pd.Timestamp | None = None) -> pd.DataFrame:
        if not self.rows:
            return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="open_time"))
        df = pd.DataFrame.from_dict(self.rows, orient="index")[COLS].sort_index()
        df.index.name = "open_time"
        return df if start is None else df[df.index >= start]

    # ---------------------------------------------------------------- persistence
    def _path(self, day: pd.Timestamp) -> Path:
        return self.root / f"{self.symbol}-1m-{day:%Y-%m-%d}.parquet"

    def flush(self) -> None:
        df = self.frame()
        for day in sorted(self._dirty_days):
            part = df[(df.index >= day) & (df.index < day + pd.Timedelta(days=1))]
            if len(part):
                self.root.mkdir(parents=True, exist_ok=True)
                part.reset_index().to_parquet(self._path(day), index=False)
        self._dirty_days.clear()

    def load(self, since: pd.Timestamp | None = None) -> None:
        if not self.root.exists():
            return
        for p in sorted(self.root.glob(f"{self.symbol}-1m-*.parquet")):
            day = pd.Timestamp(p.stem.rsplit("-1m-", 1)[1], tz="UTC")
            if since is not None and day + pd.Timedelta(days=1) <= since:
                continue
            try:
                df = pd.read_parquet(p).set_index("open_time")
            except Exception as e:     # partial write during a crash
                logging.getLogger("live_momentum").warning("unreadable bar file %s skipped: %s", p, e)
                continue
            for t, r in df[COLS].iterrows():
                self.rows.setdefault(t, r.to_dict())

    def prune(self, before: pd.Timestamp) -> None:
        """Drop in-memory bars older than `before` (files stay on disk)."""
        for t in [t for t in self.rows if t < before]:
            del self.rows[t]


def merged_history(archive: pd.DataFrame | None, live: pd.DataFrame) -> pd.DataFrame:
    """Archive bars take precedence; live bars only extend after the archive. Regular grid.
    Outage bars already marked `filled` in the archive keep the flag."""
    parts, was_filled = [], None
    if archive is not None and len(archive):
        parts.append(archive[COLS])
        if "filled" in archive:
            was_filled = archive["filled"]
        live = live[live.index > archive.index[-1]]
    if len(live):
        parts.append(live[COLS])
    if not parts:
        raise ValueError("no bars")
    out = regularize(pd.concat(parts))
    if was_filled is not None:
        out["filled"] = out["filled"] | was_filled.reindex(out.index, fill_value=False).astype(bool)
    return out
