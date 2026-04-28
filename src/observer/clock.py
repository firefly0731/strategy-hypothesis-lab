"""Triple-timestamp envelope helper.

Every captured event carries:
- server_ts_ms  : timestamp the exchange placed on the event
- recv_monotonic_ns : observer process monotonic clock at receipt
- recv_utc_ms   : observer wall clock UTC at receipt (debug/replay)

Analysis prefers recv_monotonic_ns to absorb network jitter and clock drift.
"""
from __future__ import annotations

import time
from typing import Any, TypedDict


class Envelope(TypedDict):
    channel: str
    server_ts_ms: int
    recv_monotonic_ns: int
    recv_utc_ms: int
    raw: Any


def stamp(*, channel: str, server_ts_ms: int, raw: Any) -> Envelope:
    return Envelope(
        channel=channel,
        server_ts_ms=server_ts_ms,
        recv_monotonic_ns=time.monotonic_ns(),
        recv_utc_ms=time.time_ns() // 1_000_000,
        raw=raw,
    )
