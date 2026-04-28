"""Post-capture JSONL → Parquet conversion + quality report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator


def iter_jsonl_lines(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from a JSONL file, skipping the last line if it is
    truncated (no trailing newline) and any single-line JSON parse errors."""
    data = path.read_bytes()
    if not data:
        return
    # Determine whether the file ends with a newline.
    trailing_newline = data.endswith(b"\n")
    lines = data.splitlines()
    if not trailing_newline and lines:
        lines = lines[:-1]  # drop possibly-truncated last line
    for line in lines:
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue
