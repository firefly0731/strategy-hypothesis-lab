"""Async per-channel JSONL writer with hourly file rotation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
import orjson

from observer.clock import Envelope


class Writer:
    """One Writer per channel; owns its asyncio.Queue and a rotating file handle."""

    _SENTINEL: Any = object()

    def __init__(self, *, channel: str, run_dir: Path, queue_maxsize: int = 0) -> None:
        self.channel = channel
        self.run_dir = run_dir
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task | None = None
        self._file = None
        self._open_hour: str | None = None

    async def start(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._run(), name=f"writer:{self.channel}")

    async def enqueue(self, env: Envelope) -> None:
        await self.queue.put(env)

    async def close(self) -> None:
        await self.queue.put(self._SENTINEL)
        if self._task:
            await self._task

    async def _run(self) -> None:
        try:
            while True:
                item = await self.queue.get()
                if item is self._SENTINEL:
                    self.queue.task_done()
                    break
                hour_key = self._hour_key_for(item)
                if hour_key != self._open_hour:
                    await self._rotate(hour_key)
                line = orjson.dumps(item) + b"\n"
                await self._file.write(line)
                self.queue.task_done()
        finally:
            await self._close_file()

    def _hour_key_for(self, env: Envelope) -> str:
        ts_ms = env["recv_utc_ms"]
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H")

    async def _rotate(self, hour_key: str) -> None:
        await self._close_file()
        path = self.run_dir / f"{self.channel}_{hour_key}.jsonl"
        self._file = await aiofiles.open(path, "ab")
        self._open_hour = hour_key

    async def _close_file(self) -> None:
        if self._file is not None:
            await self._file.flush()
            try:
                import os
                os.fsync(self._file.fileno())
            except Exception:
                pass
            await self._file.close()
            self._file = None
            self._open_hour = None
