"""Exponential backoff with sustain-based reset.

Sequence: start, start*2, start*4, … capped at `cap`.
If a connection lasts longer than `sustain_reset_sec`, the next disconnect
restarts the sequence at `start`. This avoids retry storms while still
responding quickly to transient failures.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class ExponentialBackoff:
    start: float
    cap: float
    sustain_reset_sec: float
    _attempt: int = 0
    _last_connected_at: float | None = None

    def next_delay(self, now: float | None = None) -> float:
        now = now if now is not None else time.monotonic()
        if (
            self._last_connected_at is not None
            and now - self._last_connected_at >= self.sustain_reset_sec
        ):
            self._attempt = 0
            self._last_connected_at = None
        delay = min(self.start * (2 ** self._attempt), self.cap)
        self._attempt += 1
        return delay

    def mark_connected(self, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        self._last_connected_at = now
