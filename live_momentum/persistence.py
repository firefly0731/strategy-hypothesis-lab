"""State snapshots (atomic JSON) and the append-only event log (JSON lines).

Neither ever contains credentials: callers pass plain trading data, and `EventLog` refuses
keys that look like secrets as a second line of defence.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

FORBIDDEN = ("api_key", "api_secret", "secret", "signature", "x-mbx-apikey")


def atomic_write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(path: Path):
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _check(obj, depth=0):
    if depth > 50:
        raise ValueError("event too deeply nested to check for secrets")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(f in str(k).lower() for f in FORBIDDEN):
                raise ValueError(f"refusing to log field {k!r}")
            _check(v, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _check(v, depth + 1)


class EventLog:
    """One JSON object per line: {"ts": epoch_ms, "type": ..., ...}."""

    def __init__(self, path: Path, clock_ms=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def write(self, type_: str, **fields) -> dict:
        rec = {"ts": self.clock_ms(), "type": type_, **fields}
        _check(rec)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for i, x in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            if not x.strip():
                continue
            try:
                out.append(json.loads(x))
            except json.JSONDecodeError:
                logging.getLogger("live_momentum").warning("%s line %d: unreadable JSON skipped", self.path, i + 1)
        return out
