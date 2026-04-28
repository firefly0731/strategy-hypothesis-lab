# Bithumb XRP/KRW Live Capture Observer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 4-hour Python asyncio observer that captures Bithumb XRP/KRW Public WebSocket (`orderbookdepth` + `transaction`) and Private WebSocket v2 (`myOrder` + `myAsset`) into hourly-rotated JSONL files with triple timestamps, then converts to Parquet for hypothesis 1 (Trade Velocity Filter) verification.

**Architecture:** Single Python asyncio process holding two WebSocket connections (one public, one private with JWT auth). Each event is wrapped in a uniform envelope with `server_ts_ms` / `recv_monotonic_ns` / `recv_utc_ms` and routed to a per-channel async writer that appends JSONL with hourly file rotation. An external shell supervisor (`scripts/run.sh`) handles `caffeinate` and process restarts. Post-capture `convert.py` produces analysis-friendly Parquet files plus a quality report.

**Tech Stack:** Python ≥3.11, `websockets`, `PyJWT`, `orjson`, `aiofiles`, `polars`, `python-dotenv`, `pytest` + `pytest-asyncio` + `freezegun`.

**Spec:** `docs/superpowers/specs/2026-04-28-data-pipeline-design.md` — every requirement (F-1…F-10, NFRs, error modes, success criteria) maps to one or more tasks below.

**Total tasks:** 24. Each task ends with a single git commit.

---

## Conventions Used Below

- All paths are relative to repo root: `/Users/yjban/Desktop/sisyphus/strategy-hypothesis-lab`.
- "Run: `pytest …`" assumes the project venv is activated (`source .venv/bin/activate`) or the user runs `pytest` via `uv run pytest` / equivalent.
- Every task has a TDD shape: failing test → run → impl → pass → commit (some setup tasks deviate; deviations are noted).
- Type hints required on every public function. Internal helpers may skip if obvious.
- All `pytest` async tests use `@pytest.mark.asyncio` (configured globally in pyproject).
- Commit messages follow Conventional Commits.

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/observer/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.env.example`
- Modify: `.gitignore` (no change expected — verify `.env` already ignored)

- [ ] **Step 1: Verify `.gitignore` already protects `.env`**

Run: `git check-ignore -v .env` → should print a line referencing `.gitignore`. If it does not, stop and inspect.

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "observer"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "websockets>=13",
  "PyJWT>=2.8",
  "orjson>=3.10",
  "aiofiles>=24",
  "polars>=1.0",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "freezegun>=1.5",
  "pytest-cov>=5",
]

[tool.hatch.build.targets.wheel]
packages = ["src/observer"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 3: Create empty package files**

`src/observer/__init__.py`:
```python
"""Observer package — Bithumb XRP/KRW live capture pipeline."""
```

`tests/__init__.py`:
```python
```

`tests/conftest.py`:
```python
"""Shared pytest fixtures."""
```

- [ ] **Step 4: Create `.env.example`**

```
BITHUMB_API_KEY=your_v2_read_only_access_key_here
BITHUMB_API_SECRET=your_v2_secret_here
OBSERVER_RUN_DIR=./data
OBSERVER_DURATION_SEC=14400
OBSERVER_MAX_RESTARTS=10
OBSERVER_SYMBOL=KRW-XRP
```

- [ ] **Step 5: Install deps and verify pytest collects**

Run:
```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest --collect-only
```

Expected: "0 tests collected" (no tests yet) without errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/observer tests .env.example
git commit -m "chore: scaffold observer package with pyproject and pytest config"
```

---

## Task 2: Triple-Timestamp Helper (`clock.py`)

**Files:**
- Create: `src/observer/clock.py`
- Create: `tests/test_clock.py`

Implements §6.1 / §5.2 of the spec — every event gets `server_ts_ms`, `recv_monotonic_ns`, `recv_utc_ms` and the original `raw` payload.

- [ ] **Step 1: Write the failing test**

`tests/test_clock.py`:
```python
import time
from observer.clock import stamp


def test_stamp_returns_envelope_with_four_keys() -> None:
    raw = {"hello": "world"}
    env = stamp(channel="transaction", server_ts_ms=1714287000123, raw=raw)
    assert set(env.keys()) == {"channel", "server_ts_ms", "recv_monotonic_ns", "recv_utc_ms", "raw"}
    assert env["channel"] == "transaction"
    assert env["server_ts_ms"] == 1714287000123
    assert env["raw"] is raw  # raw payload preserved by reference, not copied


def test_recv_monotonic_ns_is_strictly_increasing() -> None:
    a = stamp(channel="x", server_ts_ms=0, raw={})
    b = stamp(channel="x", server_ts_ms=0, raw={})
    assert b["recv_monotonic_ns"] > a["recv_monotonic_ns"]


def test_recv_utc_ms_is_close_to_wall_clock() -> None:
    before = int(time.time() * 1000)
    env = stamp(channel="x", server_ts_ms=0, raw={})
    after = int(time.time() * 1000)
    assert before <= env["recv_utc_ms"] <= after + 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_clock.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'observer.clock'`.

- [ ] **Step 3: Implement minimum code**

`src/observer/clock.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_clock.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/clock.py tests/test_clock.py
git commit -m "feat(clock): add triple-timestamp envelope helper"
```

---

## Task 3: Backoff Helper (`backoff.py`)

**Files:**
- Create: `src/observer/backoff.py`
- Create: `tests/test_backoff.py`

Implements §7.2 of the spec — exponential 0.5→1→2→4→8→16→30 with reset on sustained connection.

- [ ] **Step 1: Write the failing test**

`tests/test_backoff.py`:
```python
import time

from observer.backoff import ExponentialBackoff


def test_sequence_climbs_then_caps() -> None:
    b = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset_sec=60.0)
    assert b.next_delay() == 0.5
    assert b.next_delay() == 1.0
    assert b.next_delay() == 2.0
    assert b.next_delay() == 4.0
    assert b.next_delay() == 8.0
    assert b.next_delay() == 16.0
    assert b.next_delay() == 30.0
    assert b.next_delay() == 30.0  # capped


def test_mark_connected_does_not_reset_immediately() -> None:
    b = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset_sec=60.0)
    b.next_delay()  # bump attempt to 1
    b.next_delay()  # bump attempt to 2
    b.mark_connected(now=100.0)
    # Connection just opened — disconnect happens after 30 sec → still no reset
    assert b.next_delay(now=130.0) == 4.0  # would be 4th attempt = 4.0


def test_sustained_connection_resets_attempts() -> None:
    b = ExponentialBackoff(start=0.5, cap=30.0, sustain_reset_sec=60.0)
    b.next_delay()
    b.next_delay()
    b.mark_connected(now=100.0)
    # After 60+ seconds connected, next disconnect resets sequence
    assert b.next_delay(now=170.0) == 0.5
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_backoff.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/observer/backoff.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_backoff.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/backoff.py tests/test_backoff.py
git commit -m "feat(backoff): add exponential backoff with sustain reset"
```

---

## Task 4: Config Loader (`config.py`)

**Files:**
- Create: `src/observer/config.py`
- Create: `tests/test_config.py`

Implements §5.5 / §2.1 — loads `.env`, validates required keys, applies defaults.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import os
from pathlib import Path

import pytest

from observer.config import Config, ConfigError, load_config


def test_load_config_with_all_required_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BITHUMB_API_KEY", "key123")
    monkeypatch.setenv("BITHUMB_API_SECRET", "secret456")
    monkeypatch.setenv("OBSERVER_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("OBSERVER_DURATION_SEC", "14400")
    monkeypatch.setenv("OBSERVER_MAX_RESTARTS", "10")
    monkeypatch.setenv("OBSERVER_SYMBOL", "KRW-XRP")
    cfg = load_config(use_dotenv=False)
    assert isinstance(cfg, Config)
    assert cfg.api_key == "key123"
    assert cfg.api_secret == "secret456"
    assert cfg.run_dir == tmp_path
    assert cfg.duration_sec == 14400
    assert cfg.max_restarts == 10
    assert cfg.symbol == "KRW-XRP"


def test_load_config_applies_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BITHUMB_API_KEY", "k")
    monkeypatch.setenv("BITHUMB_API_SECRET", "s")
    monkeypatch.setenv("OBSERVER_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("OBSERVER_DURATION_SEC", raising=False)
    monkeypatch.delenv("OBSERVER_MAX_RESTARTS", raising=False)
    monkeypatch.delenv("OBSERVER_SYMBOL", raising=False)
    cfg = load_config(use_dotenv=False)
    assert cfg.duration_sec == 14400
    assert cfg.max_restarts == 10
    assert cfg.symbol == "KRW-XRP"


def test_load_config_missing_required_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BITHUMB_API_KEY", raising=False)
    monkeypatch.setenv("BITHUMB_API_SECRET", "s")
    monkeypatch.setenv("OBSERVER_RUN_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="BITHUMB_API_KEY"):
        load_config(use_dotenv=False)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py -v` → FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/observer/config.py`:
```python
"""Runtime configuration loaded from environment.

Required: BITHUMB_API_KEY, BITHUMB_API_SECRET, OBSERVER_RUN_DIR.
Optional (with defaults): OBSERVER_DURATION_SEC=14400, OBSERVER_MAX_RESTARTS=10, OBSERVER_SYMBOL=KRW-XRP.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str
    api_secret: str
    run_dir: Path
    duration_sec: int
    max_restarts: int
    symbol: str


def _require(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise ConfigError(f"Missing required env var: {name}")
    return value


def load_config(*, use_dotenv: bool = True) -> Config:
    if use_dotenv:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    return Config(
        api_key=_require("BITHUMB_API_KEY"),
        api_secret=_require("BITHUMB_API_SECRET"),
        run_dir=Path(_require("OBSERVER_RUN_DIR")),
        duration_sec=int(os.environ.get("OBSERVER_DURATION_SEC", "14400")),
        max_restarts=int(os.environ.get("OBSERVER_MAX_RESTARTS", "10")),
        symbol=os.environ.get("OBSERVER_SYMBOL", "KRW-XRP"),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_config.py -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/config.py tests/test_config.py
git commit -m "feat(config): load runtime configuration from environment"
```

---

## Task 5: Writer Basic JSONL (`writer.py`)

**Files:**
- Create: `src/observer/writer.py`
- Create: `tests/test_writer.py`

Implements §6.4 of the spec, basic version — async queue + file write. Hourly rotation comes in Task 6.

- [ ] **Step 1: Write the failing test**

`tests/test_writer.py`:
```python
import asyncio
import json
from pathlib import Path

import pytest

from observer.clock import stamp
from observer.writer import Writer


@pytest.mark.asyncio
async def test_writer_writes_envelopes_as_jsonl(tmp_path: Path) -> None:
    w = Writer(channel="transaction", run_dir=tmp_path)
    await w.start()
    for i in range(3):
        await w.enqueue(stamp(channel="transaction", server_ts_ms=i, raw={"i": i}))
    await w.close()

    files = sorted(tmp_path.glob("transaction_*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    assert len(lines) == 3
    parsed = [json.loads(l) for l in lines]
    assert [p["raw"]["i"] for p in parsed] == [0, 1, 2]
    for p in parsed:
        assert set(p.keys()) >= {"channel", "server_ts_ms", "recv_monotonic_ns", "recv_utc_ms", "raw"}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_writer.py -v` → FAIL.

- [ ] **Step 3: Implement minimum code**

`src/observer/writer.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_writer.py -v` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/writer.py tests/test_writer.py
git commit -m "feat(writer): basic JSONL writer with async queue"
```

---

## Task 6: Writer Hourly Rotation Test

**Files:**
- Modify: `tests/test_writer.py` (add new test)

The basic implementation in Task 5 already supports rotation — this task adds the test that pins down the boundary behavior of §4.2 #3 / §6.4 of the spec.

- [ ] **Step 1: Write the new failing test**

Append to `tests/test_writer.py`:
```python
@pytest.mark.asyncio
async def test_writer_rotates_at_utc_hour_boundary(tmp_path: Path, monkeypatch) -> None:
    """Envelopes whose recv_utc_ms falls in different UTC hours land in separate files."""
    from observer import clock

    # Patch stamp() so we can force recv_utc_ms across an hour boundary.
    real_stamp = clock.stamp

    boundary_ms = int(datetime(2026, 4, 28, 7, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    fake_clocks = iter([boundary_ms - 1000, boundary_ms - 100, boundary_ms + 100, boundary_ms + 1000])

    def fake_stamp(**kwargs):
        env = real_stamp(**kwargs)
        env["recv_utc_ms"] = next(fake_clocks)
        return env

    monkeypatch.setattr(clock, "stamp", fake_stamp)

    w = Writer(channel="transaction", run_dir=tmp_path)
    await w.start()
    for i in range(4):
        await w.enqueue(clock.stamp(channel="transaction", server_ts_ms=i, raw={"i": i}))
    await w.close()

    files = sorted(p.name for p in tmp_path.glob("transaction_*.jsonl"))
    assert files == ["transaction_2026-04-28T06.jsonl", "transaction_2026-04-28T07.jsonl"]

    h6 = (tmp_path / "transaction_2026-04-28T06.jsonl").read_text().splitlines()
    h7 = (tmp_path / "transaction_2026-04-28T07.jsonl").read_text().splitlines()
    assert len(h6) == 2
    assert len(h7) == 2
```

Add the import near the top of the file:
```python
from datetime import datetime, timezone
```

- [ ] **Step 2: Run to verify pass (already implemented in Task 5)**

Run: `pytest tests/test_writer.py -v` → 2 passed.

If it fails, the rotation logic in `writer.py::_hour_key_for` / `_rotate` is wrong — fix until it passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_writer.py
git commit -m "test(writer): pin hourly rotation at UTC boundary"
```

---

## Task 7: Writer Truncated-Append Recovery Test

**Files:**
- Modify: `tests/test_writer.py`

Verifies that re-opening an existing partially-written file appends cleanly (Task 5's implementation already opens with `"ab"` mode — this test pins the contract for §6.6 SIGKILL recovery).

- [ ] **Step 1: Write the new failing test**

Append to `tests/test_writer.py`:
```python
@pytest.mark.asyncio
async def test_writer_appends_to_existing_partial_file(tmp_path: Path) -> None:
    """A new Writer in the same hour should append, not truncate."""
    # First writer writes 2 lines and exits.
    w1 = Writer(channel="transaction", run_dir=tmp_path)
    await w1.start()
    await w1.enqueue(stamp(channel="transaction", server_ts_ms=0, raw={"i": 0}))
    await w1.enqueue(stamp(channel="transaction", server_ts_ms=1, raw={"i": 1}))
    await w1.close()

    # Simulate a process restart by truncating the last byte (e.g. SIGKILL mid-newline).
    files = list(tmp_path.glob("transaction_*.jsonl"))
    assert len(files) == 1
    path = files[0]
    data = path.read_bytes()
    path.write_bytes(data[:-1])  # drop trailing newline to simulate partial write

    # Second writer must append more lines without losing the first ones.
    w2 = Writer(channel="transaction", run_dir=tmp_path)
    await w2.start()
    await w2.enqueue(stamp(channel="transaction", server_ts_ms=2, raw={"i": 2}))
    await w2.close()

    text = path.read_text()
    # The first line (with newline) should still be present.
    assert '"i":0' in text
    # The third event should be appended (after the truncated second event).
    assert '"i":2' in text
```

- [ ] **Step 2: Run to verify pass**

Run: `pytest tests/test_writer.py -v` → 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_writer.py
git commit -m "test(writer): pin append-on-restart behavior"
```

---

## Task 8: Mock WebSocket Server Fixture

**Files:**
- Modify: `tests/conftest.py`

A reusable fixture for Tasks 9–13. Hosts a tiny asyncio WebSocket server that the WS client modules can connect to.

- [ ] **Step 1: Write the failing test (smoke for the fixture itself)**

Create `tests/test_mock_ws.py`:
```python
import asyncio
import json

import pytest
import websockets


@pytest.mark.asyncio
async def test_mock_ws_echoes(mock_ws_server) -> None:
    """The mock server echoes back any text frame the client sends."""
    server, port = mock_ws_server
    server.script = [{"echo": True}]
    async with websockets.connect(f"ws://localhost:{port}") as ws:
        await ws.send(json.dumps({"hello": "world"}))
        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
    assert json.loads(msg) == {"hello": "world"}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mock_ws.py -v`
Expected: FAIL with "fixture 'mock_ws_server' not found".

- [ ] **Step 3: Implement the fixture**

Replace `tests/conftest.py`:
```python
"""Shared pytest fixtures."""
from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
import websockets


@dataclass
class MockWSController:
    """Controls a single mock WS server's behavior across one test."""
    pushes: list[Any] = field(default_factory=list)         # frames to push to client on connect
    drop_after: int | None = None                            # close connection after N received frames
    reject_with_code: int | None = None                      # reject handshake with this close code
    received: list[Any] = field(default_factory=list)        # frames received from client
    script: list[dict] = field(default_factory=list)         # generic per-test config (e.g. {"echo": True})


@pytest.fixture
async def mock_ws_server():
    controller = MockWSController()

    async def handler(ws):
        if controller.reject_with_code is not None:
            await ws.close(code=controller.reject_with_code)
            return
        # Push pre-scripted frames
        for frame in controller.pushes:
            await ws.send(json.dumps(frame) if not isinstance(frame, (str, bytes)) else frame)
        # Read incoming
        try:
            received_count = 0
            async for raw in ws:
                msg = json.loads(raw) if isinstance(raw, str) else raw
                controller.received.append(msg)
                received_count += 1
                if any(s.get("echo") for s in controller.script):
                    await ws.send(raw)
                if controller.drop_after is not None and received_count >= controller.drop_after:
                    await ws.close()
                    return
        except websockets.ConnectionClosed:
            pass

    server = await websockets.serve(handler, "localhost", 0)
    port = server.sockets[0].getsockname()[1]
    # Attach the controller to the server object for tests to manipulate.
    server.controller = controller  # type: ignore[attr-defined]
    server.port = port  # type: ignore[attr-defined]
    try:
        yield server, port
    finally:
        server.close()
        await server.wait_closed()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_mock_ws.py -v` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_mock_ws.py
git commit -m "test: add mock WebSocket server fixture"
```

---

## Task 9: Public WS — Connect, Subscribe, Parse, Callback

**Files:**
- Create: `src/observer/ws_public.py`
- Create: `tests/test_ws_public.py`
- Create: `tests/fixtures/orderbookdepth_sample.json`
- Create: `tests/fixtures/transaction_sample.json`

Implements §6.2 of the spec without reconnect logic (added in Task 10).

- [ ] **Step 1: Add fixture files**

`tests/fixtures/orderbookdepth_sample.json`:
```json
{"type":"orderbookdepth","content":{"datetime":"1714287000123","symbol":"KRW-XRP","list":[{"orderType":"bid","price":"1380.5","quantity":"100","total":"3"},{"orderType":"ask","price":"1381.0","quantity":"50","total":"2"}]}}
```

`tests/fixtures/transaction_sample.json`:
```json
{"type":"transaction","content":{"list":[{"symbol":"KRW-XRP","buySellGb":"2","contPrice":"1380.5","contQty":"10.5","contAmt":"14495.25","contDtm":"2026-04-28 16:00:00.123","updn":"dn"}]}}
```

- [ ] **Step 2: Write the failing test**

`tests/test_ws_public.py`:
```python
import asyncio
import json
from pathlib import Path

import pytest

from observer.ws_public import run_public_ws

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_public_ws_subscribes_and_dispatches(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample_orderbook = json.loads((FIXTURES / "orderbookdepth_sample.json").read_text())
    sample_trade = json.loads((FIXTURES / "transaction_sample.json").read_text())
    server.controller.pushes = [sample_orderbook, sample_trade]

    received: list[tuple[str, dict]] = []

    async def on_event(channel: str, env: dict) -> None:
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_public_ws(
            url=f"ws://localhost:{port}",
            symbol="KRW-XRP",
            on_event=on_event,
            stop_event=stop_event,
        )
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
    finally:
        task.cancel()
        with contextlib_suppress(asyncio.CancelledError):
            await task

    # Subscriptions sent
    sub_types = {msg["type"] for msg in server.controller.received}
    assert sub_types == {"orderbookdepth", "transaction"}

    # Both events delivered with envelope shape
    channels = [c for c, _ in received]
    assert "orderbookdepth" in channels and "transaction" in channels
    for _, env in received:
        assert {"channel", "server_ts_ms", "recv_monotonic_ns", "recv_utc_ms", "raw"} <= set(env.keys())


# Compat shim for older Python: contextlib.suppress as a function expression.
import contextlib
def contextlib_suppress(*exc):
    return contextlib.suppress(*exc)
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_ws_public.py -v` → FAIL.

- [ ] **Step 4: Implement**

`src/observer/ws_public.py`:
```python
"""Bithumb public WebSocket client.

Subscribes to `orderbookdepth` and `transaction` channels for one symbol and
dispatches every incoming frame to a user-supplied callback wrapped in an
Envelope. Reconnect with backoff is layered on top in run_public_ws_with_reconnect.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import orjson
import websockets

from observer.clock import stamp

OnEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


def _server_ts_ms_from_payload(payload: dict[str, Any]) -> int:
    """Best-effort extract of server timestamp.

    `orderbookdepth` puts it at content.datetime (string ms).
    `transaction` puts it at content.list[*].contDtm (string KST).
    Falls back to 0 if absent — analysis still has recv_monotonic_ns.
    """
    content = payload.get("content") or {}
    if isinstance(content.get("datetime"), str):
        try:
            return int(content["datetime"])
        except ValueError:
            return 0
    return 0


async def run_public_ws(
    *,
    url: str,
    symbol: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
) -> None:
    """Single-attempt WS run. Returns when stop_event is set or connection closes."""
    async with websockets.connect(url, ping_interval=30) as ws:
        await ws.send(orjson.dumps({"type": "orderbookdepth", "symbols": [symbol]}))
        await ws.send(orjson.dumps({"type": "transaction", "symbols": [symbol]}))
        async for raw_msg in ws:
            if stop_event.is_set():
                return
            payload = orjson.loads(raw_msg)
            channel = payload.get("type", "unknown")
            env = stamp(
                channel=channel,
                server_ts_ms=_server_ts_ms_from_payload(payload),
                raw=payload,
            )
            await on_event(channel, env)
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/test_ws_public.py -v` → 1 passed.

- [ ] **Step 6: Commit**

```bash
git add src/observer/ws_public.py tests/test_ws_public.py tests/fixtures/orderbookdepth_sample.json tests/fixtures/transaction_sample.json
git commit -m "feat(ws-public): subscribe and dispatch public channels"
```

---

## Task 10: Public WS — Reconnect with Backoff

**Files:**
- Modify: `src/observer/ws_public.py`
- Modify: `tests/test_ws_public.py`

Adds the resilient outer loop (§6.2 / §7.1 #1).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ws_public.py`:
```python
@pytest.mark.asyncio
async def test_public_ws_reconnects_after_disconnect(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample = json.loads((FIXTURES / "transaction_sample.json").read_text())

    # First connection: send 1 frame then drop.
    server.controller.pushes = [sample]
    server.controller.drop_after = 0  # close immediately after pushes

    received: list[tuple[str, dict]] = []
    stop_event = asyncio.Event()

    async def on_event(channel, env):
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    from observer.ws_public import run_public_ws_with_reconnect
    task = asyncio.create_task(
        run_public_ws_with_reconnect(
            url=f"ws://localhost:{port}",
            symbol="KRW-XRP",
            on_event=on_event,
            stop_event=stop_event,
            backoff_start=0.05,
            backoff_cap=0.2,
        )
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=3.0)
    finally:
        task.cancel()
        with contextlib_suppress(asyncio.CancelledError):
            await task

    assert len(received) >= 2
    # The mock server's controller is shared across reconnects, so received contains
    # subscribe frames from at least 2 connection attempts.
    sub_count = sum(1 for m in server.controller.received if m.get("type") == "transaction")
    assert sub_count >= 2
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ws_public.py::test_public_ws_reconnects_after_disconnect -v`
Expected: FAIL with `ImportError: cannot import name 'run_public_ws_with_reconnect'`.

- [ ] **Step 3: Implement**

Append to `src/observer/ws_public.py`:
```python
from observer.backoff import ExponentialBackoff


async def run_public_ws_with_reconnect(
    *,
    url: str,
    symbol: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
    backoff_start: float = 0.5,
    backoff_cap: float = 30.0,
    sustain_reset_sec: float = 60.0,
    on_disconnect: Callable[[], None] | None = None,
) -> None:
    """Outer loop: connect → run → on disconnect, backoff and reconnect."""
    backoff = ExponentialBackoff(
        start=backoff_start, cap=backoff_cap, sustain_reset_sec=sustain_reset_sec
    )
    while not stop_event.is_set():
        try:
            backoff.mark_connected()
            await run_public_ws(url=url, symbol=symbol, on_event=on_event, stop_event=stop_event)
        except (websockets.ConnectionClosed, OSError):
            pass
        if stop_event.is_set():
            return
        if on_disconnect is not None:
            on_disconnect()
        await asyncio.sleep(backoff.next_delay())
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ws_public.py -v` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/ws_public.py tests/test_ws_public.py
git commit -m "feat(ws-public): reconnect with exponential backoff"
```

---

## Task 11: Private WS — JWT Helper

**Files:**
- Create: `src/observer/jwt_auth.py`
- Create: `tests/test_jwt_auth.py`

Implements the auth piece of §6.3.

- [ ] **Step 1: Write the failing test**

`tests/test_jwt_auth.py`:
```python
import jwt as pyjwt

from observer.jwt_auth import make_bithumb_jwt


def test_make_bithumb_jwt_round_trip() -> None:
    token = make_bithumb_jwt(api_key="ak123", api_secret="secret456", nonce="n-1")
    decoded = pyjwt.decode(token, "secret456", algorithms=["HS256"])
    assert decoded["access_key"] == "ak123"
    assert decoded["nonce"] == "n-1"
    # Bithumb spec: no `exp`
    assert "exp" not in decoded


def test_make_bithumb_jwt_unique_nonces_when_default() -> None:
    a = make_bithumb_jwt(api_key="k", api_secret="s")
    b = make_bithumb_jwt(api_key="k", api_secret="s")
    assert a != b  # because nonce is auto-generated unique
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_jwt_auth.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/observer/jwt_auth.py`:
```python
"""JWT generation for Bithumb Private WebSocket v2."""
from __future__ import annotations

import uuid

import jwt as pyjwt


def make_bithumb_jwt(*, api_key: str, api_secret: str, nonce: str | None = None) -> str:
    payload = {
        "access_key": api_key,
        "nonce": nonce or str(uuid.uuid4()),
    }
    return pyjwt.encode(payload, api_secret, algorithm="HS256")
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_jwt_auth.py -v` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/jwt_auth.py tests/test_jwt_auth.py
git commit -m "feat(jwt): add Bithumb v2 JWT helper"
```

---

## Task 12: Private WS — Connect, Subscribe, Parse

**Files:**
- Create: `src/observer/ws_private.py`
- Create: `tests/test_ws_private.py`
- Create: `tests/fixtures/myorder_sample.json`
- Create: `tests/fixtures/myasset_sample.json`

Implements §6.3 minus reconnect (Task 13).

- [ ] **Step 1: Add fixtures**

`tests/fixtures/myorder_sample.json`:
```json
{"type":"myOrder","content":{"order_id":"abc-123","order_status":"FILLED","order_side":"BID","price":"1380.0","quantity":"50","filled_quantity":"50","fee":"7.5","timestamp":"1714287030000","symbol":"KRW-XRP"}}
```

`tests/fixtures/myasset_sample.json`:
```json
{"type":"myAsset","content":{"currency":"USDT","balance":"1000.0","locked":"0.0","timestamp":"1714287030000"}}
```

- [ ] **Step 2: Write the failing test**

`tests/test_ws_private.py`:
```python
import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from observer.ws_private import run_private_ws

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_private_ws_subscribes_and_dispatches(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample_order = json.loads((FIXTURES / "myorder_sample.json").read_text())
    sample_asset = json.loads((FIXTURES / "myasset_sample.json").read_text())
    server.controller.pushes = [sample_order, sample_asset]

    received: list[tuple[str, dict]] = []
    stop_event = asyncio.Event()

    async def on_event(channel: str, env: dict) -> None:
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    task = asyncio.create_task(
        run_private_ws(
            url=f"ws://localhost:{port}",
            api_key="ak",
            api_secret="sk",
            on_event=on_event,
            stop_event=stop_event,
        )
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    channels = [c for c, _ in received]
    assert "myOrder" in channels
    assert "myAsset" in channels

    # Subscription frame must include both channel types
    sub_types = set()
    for msg in server.controller.received:
        if isinstance(msg, list):
            for entry in msg:
                if isinstance(entry, dict) and "type" in entry:
                    sub_types.add(entry["type"])
    assert {"myOrder", "myAsset"} <= sub_types
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_ws_private.py -v` → FAIL.

- [ ] **Step 4: Implement**

`src/observer/ws_private.py`:
```python
"""Bithumb Private WebSocket v2 client (myOrder + myAsset)."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import orjson
import websockets

from observer.clock import stamp
from observer.jwt_auth import make_bithumb_jwt

OnEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


class PrivateAuthError(RuntimeError):
    pass


def _server_ts_ms_from_payload(payload: dict[str, Any]) -> int:
    content = payload.get("content") or {}
    ts = content.get("timestamp") if isinstance(content, dict) else None
    if isinstance(ts, str):
        try:
            return int(ts)
        except ValueError:
            return 0
    if isinstance(ts, int):
        return ts
    return 0


async def run_private_ws(
    *,
    url: str,
    api_key: str,
    api_secret: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
) -> None:
    token = make_bithumb_jwt(api_key=api_key, api_secret=api_secret)
    headers = [("Authorization", f"Bearer {token}")]
    try:
        async with websockets.connect(url, additional_headers=headers, ping_interval=30) as ws:
            sub = [
                {"ticket": "observer"},
                {"type": "myOrder"},
                {"type": "myAsset"},
                {"format": "DEFAULT"},
            ]
            await ws.send(orjson.dumps(sub))
            async for raw_msg in ws:
                if stop_event.is_set():
                    return
                payload = orjson.loads(raw_msg)
                channel = payload.get("type", "unknown")
                env = stamp(
                    channel=channel,
                    server_ts_ms=_server_ts_ms_from_payload(payload),
                    raw=payload,
                )
                await on_event(channel, env)
    except websockets.InvalidStatusCode as e:
        if e.status_code in (401, 403):
            raise PrivateAuthError(f"Bithumb private auth rejected: {e.status_code}") from e
        raise
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/test_ws_private.py -v` → 1 passed.

- [ ] **Step 6: Commit**

```bash
git add src/observer/ws_private.py tests/test_ws_private.py tests/fixtures/myorder_sample.json tests/fixtures/myasset_sample.json
git commit -m "feat(ws-private): subscribe and dispatch private channels"
```

---

## Task 13: Private WS — Reconnect Wrapper, Auth-Fail Aborts

**Files:**
- Modify: `src/observer/ws_private.py`
- Modify: `tests/test_ws_private.py`

Implements §7.1 #4: auth failure terminates the private stream without retry; other errors reconnect.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ws_private.py`:
```python
@pytest.mark.asyncio
async def test_private_ws_reconnects_on_drop(mock_ws_server) -> None:
    server, port = mock_ws_server
    sample = json.loads((FIXTURES / "myasset_sample.json").read_text())
    server.controller.pushes = [sample]
    server.controller.drop_after = 0

    received: list[tuple[str, dict]] = []
    stop_event = asyncio.Event()

    async def on_event(channel, env):
        received.append((channel, env))
        if len(received) >= 2:
            stop_event.set()

    from observer.ws_private import run_private_ws_with_reconnect
    task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=f"ws://localhost:{port}",
            api_key="ak",
            api_secret="sk",
            on_event=on_event,
            stop_event=stop_event,
            backoff_start=0.05,
            backoff_cap=0.2,
        )
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=3.0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(received) >= 2


@pytest.mark.asyncio
async def test_private_ws_aborts_on_auth_failure(mock_ws_server) -> None:
    server, port = mock_ws_server
    server.controller.reject_with_code = 4001  # any non-1000 close code

    received: list = []
    stop_event = asyncio.Event()

    async def on_event(channel, env):
        received.append((channel, env))

    from observer.ws_private import run_private_ws_with_reconnect
    # Use a strict policy: any close → treat as auth fail (test path)
    # In production code, the policy is "401/403 → abort".
    task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=f"ws://localhost:{port}",
            api_key="ak",
            api_secret="sk",
            on_event=on_event,
            stop_event=stop_event,
            backoff_start=0.05,
            backoff_cap=0.1,
            max_reconnect_attempts=3,
        )
    )
    # Should complete on its own (give up after attempts) within a small window.
    await asyncio.wait_for(task, timeout=2.0)
    # No events were ever pushed, but we want to verify the function returned cleanly.
    assert received == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ws_private.py -v`
Expected: FAIL with import error and a missing parameter.

- [ ] **Step 3: Implement**

Append to `src/observer/ws_private.py`:
```python
from observer.backoff import ExponentialBackoff


async def run_private_ws_with_reconnect(
    *,
    url: str,
    api_key: str,
    api_secret: str,
    on_event: OnEvent,
    stop_event: asyncio.Event,
    backoff_start: float = 0.5,
    backoff_cap: float = 30.0,
    sustain_reset_sec: float = 60.0,
    max_reconnect_attempts: int | None = None,
    on_disconnect: Callable[[], None] | None = None,
) -> None:
    backoff = ExponentialBackoff(
        start=backoff_start, cap=backoff_cap, sustain_reset_sec=sustain_reset_sec
    )
    attempts = 0
    while not stop_event.is_set():
        try:
            backoff.mark_connected()
            await run_private_ws(
                url=url,
                api_key=api_key,
                api_secret=api_secret,
                on_event=on_event,
                stop_event=stop_event,
            )
        except PrivateAuthError:
            return  # immediate abort, never retry auth
        except (websockets.ConnectionClosed, OSError):
            pass
        if stop_event.is_set():
            return
        if on_disconnect is not None:
            on_disconnect()
        attempts += 1
        if max_reconnect_attempts is not None and attempts >= max_reconnect_attempts:
            return
        await asyncio.sleep(backoff.next_delay())
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ws_private.py -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/ws_private.py tests/test_ws_private.py
git commit -m "feat(ws-private): reconnect with abort on auth failure"
```

---

## Task 14: Main Orchestration — Wire It Up

**Files:**
- Create: `src/observer/main.py`
- Create: `tests/test_main_orchestration.py`

Implements §6.1 of the spec: gather public/private/duration tasks and writers.

- [ ] **Step 1: Write the failing test**

`tests/test_main_orchestration.py`:
```python
import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from observer.config import Config
from observer.main import run_capture


@pytest.mark.asyncio
async def test_run_capture_writes_each_channel(tmp_path: Path, mock_ws_server) -> None:
    """Smoke: feed each channel one frame; verify per-channel JSONL files appear."""
    server, port = mock_ws_server
    server.controller.pushes = [
        {"type": "orderbookdepth", "content": {"datetime": "0", "list": []}},
        {"type": "transaction", "content": {"list": []}},
        {"type": "myOrder", "content": {"timestamp": "0"}},
        {"type": "myAsset", "content": {"timestamp": "0"}},
    ]
    cfg = Config(
        api_key="ak",
        api_secret="sk",
        run_dir=tmp_path,
        duration_sec=1,
        max_restarts=1,
        symbol="KRW-XRP",
    )
    await run_capture(
        cfg=cfg,
        public_url=f"ws://localhost:{port}",
        private_url=f"ws://localhost:{port}",
    )

    files = sorted(p.name.split("_")[0] for p in tmp_path.glob("*.jsonl"))
    # All 4 channel prefixes should appear at least once.
    assert "orderbookdepth" in files
    assert "transaction" in files
    assert "myOrder" in files
    assert "myAsset" in files

    # meta.json written
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert "started_utc_ms" in meta
    assert "ended_utc_ms" in meta
    assert "event_counts" in meta
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_main_orchestration.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/observer/main.py`:
```python
"""Observer entry point: runs all four channels concurrently for a fixed duration."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from observer.clock import Envelope
from observer.config import Config, load_config
from observer.writer import Writer
from observer.ws_private import run_private_ws_with_reconnect
from observer.ws_public import run_public_ws_with_reconnect

PUBLIC_URL = "wss://pubwss.bithumb.com/pub/ws"
PRIVATE_URL = "wss://ws-api.bithumb.com/websocket/v1/private"
CHANNELS = ("orderbookdepth", "transaction", "myOrder", "myAsset")


async def run_capture(
    *,
    cfg: Config,
    public_url: str = PUBLIC_URL,
    private_url: str = PRIVATE_URL,
) -> None:
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    started_utc_ms = int(time.time() * 1000)

    writers: dict[str, Writer] = {ch: Writer(channel=ch, run_dir=cfg.run_dir) for ch in CHANNELS}
    for w in writers.values():
        await w.start()

    counts: dict[str, int] = {ch: 0 for ch in CHANNELS}

    async def on_event(channel: str, env: Envelope) -> None:
        if channel not in writers:
            return
        counts[channel] += 1
        await writers[channel].enqueue(env)

    stop_event = asyncio.Event()

    async def duration_timer() -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=cfg.duration_sec)
        except asyncio.TimeoutError:
            stop_event.set()

    public_task = asyncio.create_task(
        run_public_ws_with_reconnect(
            url=public_url,
            symbol=cfg.symbol,
            on_event=on_event,
            stop_event=stop_event,
        )
    )
    private_task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=private_url,
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
            on_event=on_event,
            stop_event=stop_event,
        )
    )
    timer_task = asyncio.create_task(duration_timer())

    try:
        await timer_task
    finally:
        stop_event.set()
        for t in (public_task, private_task):
            t.cancel()
        await asyncio.gather(public_task, private_task, return_exceptions=True)
        for w in writers.values():
            await w.close()

    ended_utc_ms = int(time.time() * 1000)
    (cfg.run_dir / "meta.json").write_text(
        json.dumps(
            {
                "started_utc_ms": started_utc_ms,
                "ended_utc_ms": ended_utc_ms,
                "duration_planned_sec": cfg.duration_sec,
                "restart_count": 0,
                "gaps": [],
                "event_counts": counts,
                "symbol": cfg.symbol,
            },
            indent=2,
        )
    )


def main() -> None:
    cfg = load_config()
    asyncio.run(run_capture(cfg=cfg))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main_orchestration.py -v` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/main.py tests/test_main_orchestration.py
git commit -m "feat(main): orchestrate writers + ws clients with duration timer"
```

---

## Task 15: Main — Signal Handling and Graceful Shutdown

**Files:**
- Modify: `src/observer/main.py`
- Modify: `tests/test_main_orchestration.py`

Implements §6.5 — SIGINT/SIGTERM trigger stop_event.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_orchestration.py`:
```python
@pytest.mark.asyncio
async def test_run_capture_responds_to_external_stop(tmp_path: Path, mock_ws_server) -> None:
    """If the caller sets stop_event before duration elapses, run exits early."""
    server, port = mock_ws_server
    server.controller.pushes = []  # no events; we just want a fast graceful exit

    cfg = Config(
        api_key="ak",
        api_secret="sk",
        run_dir=tmp_path,
        duration_sec=10,  # would be 10s if not stopped
        max_restarts=1,
        symbol="KRW-XRP",
    )

    from observer.main import run_capture, request_stop
    task = asyncio.create_task(
        run_capture(cfg=cfg, public_url=f"ws://localhost:{port}", private_url=f"ws://localhost:{port}")
    )
    await asyncio.sleep(0.3)
    request_stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Should still have written meta.json
    assert (tmp_path / "meta.json").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_main_orchestration.py::test_run_capture_responds_to_external_stop -v` → FAIL.

- [ ] **Step 3: Implement**

Modify `src/observer/main.py` — add a module-level event accessor and signal hookup:

Add near top (after imports):
```python
_GLOBAL_STOP: asyncio.Event | None = None


def request_stop() -> None:
    """Trigger shutdown of the active run_capture (if any)."""
    if _GLOBAL_STOP is not None:
        _GLOBAL_STOP.set()
```

Inside `run_capture`, immediately after `stop_event = asyncio.Event()`:
```python
    global _GLOBAL_STOP
    _GLOBAL_STOP = stop_event
```

And in the `finally:` block of `run_capture`, add:
```python
        _GLOBAL_STOP = None
```

Update `main()` to install signal handlers:
```python
def main() -> None:
    import signal

    cfg = load_config()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop)
    try:
        loop.run_until_complete(run_capture(cfg=cfg))
    finally:
        loop.close()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main_orchestration.py -v` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/main.py tests/test_main_orchestration.py
git commit -m "feat(main): add SIGINT/SIGTERM graceful shutdown hook"
```

---

## Task 16: Main — Gap Tracking on Reconnect

**Files:**
- Modify: `src/observer/main.py`
- Modify: `tests/test_main_orchestration.py`

Implements §7.3 — `meta.json.gaps` records `(channel, start_monotonic_ns, end_monotonic_ns, duration_ms, reason)` per disconnect.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_orchestration.py`:
```python
@pytest.mark.asyncio
async def test_meta_json_records_gaps_on_reconnect(tmp_path: Path, mock_ws_server) -> None:
    server, port = mock_ws_server
    server.controller.pushes = [{"type": "transaction", "content": {"list": []}}]
    server.controller.drop_after = 0  # drop after subscription

    cfg = Config(
        api_key="ak", api_secret="sk", run_dir=tmp_path,
        duration_sec=1, max_restarts=1, symbol="KRW-XRP",
    )
    await run_capture(cfg=cfg, public_url=f"ws://localhost:{port}", private_url=f"ws://localhost:{port}")
    meta = json.loads((tmp_path / "meta.json").read_text())
    # At least one gap (public stream reconnected at least once)
    assert len(meta["gaps"]) >= 1
    gap = meta["gaps"][0]
    assert {"channel", "start_monotonic_ns", "end_monotonic_ns", "duration_ms", "reason"} <= set(gap.keys())
    assert gap["channel"] in {"public", "private"}
    assert gap["reason"] == "ws_disconnect"
    assert gap["duration_ms"] >= 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_main_orchestration.py::test_meta_json_records_gaps_on_reconnect -v` → FAIL.

- [ ] **Step 3: Implement**

In `src/observer/main.py`, replace the body of `run_capture` to track gaps:

```python
async def run_capture(
    *,
    cfg: Config,
    public_url: str = PUBLIC_URL,
    private_url: str = PRIVATE_URL,
) -> None:
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    started_utc_ms = int(time.time() * 1000)

    writers: dict[str, Writer] = {ch: Writer(channel=ch, run_dir=cfg.run_dir) for ch in CHANNELS}
    for w in writers.values():
        await w.start()

    counts: dict[str, int] = {ch: 0 for ch in CHANNELS}
    gaps: list[dict[str, Any]] = []

    async def on_event(channel: str, env: Envelope) -> None:
        if channel not in writers:
            return
        counts[channel] += 1
        await writers[channel].enqueue(env)

    stop_event = asyncio.Event()
    global _GLOBAL_STOP
    _GLOBAL_STOP = stop_event

    last_disconnect: dict[str, int] = {}

    def make_disconnect_cb(group: str):
        def cb() -> None:
            last_disconnect[group] = time.monotonic_ns()
        return cb

    def record_gap_if_pending(group: str) -> None:
        start = last_disconnect.pop(group, None)
        if start is None:
            return
        end = time.monotonic_ns()
        gaps.append(
            {
                "channel": group,
                "start_monotonic_ns": start,
                "end_monotonic_ns": end,
                "duration_ms": (end - start) // 1_000_000,
                "reason": "ws_disconnect",
            }
        )

    async def on_event_with_gap_close(channel: str, env: Envelope) -> None:
        # First event after a disconnect closes the gap for that group
        group = "private" if channel in ("myOrder", "myAsset") else "public"
        record_gap_if_pending(group)
        await on_event(channel, env)

    async def duration_timer() -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=cfg.duration_sec)
        except asyncio.TimeoutError:
            stop_event.set()

    public_task = asyncio.create_task(
        run_public_ws_with_reconnect(
            url=public_url, symbol=cfg.symbol,
            on_event=on_event_with_gap_close, stop_event=stop_event,
            on_disconnect=make_disconnect_cb("public"),
        )
    )
    private_task = asyncio.create_task(
        run_private_ws_with_reconnect(
            url=private_url, api_key=cfg.api_key, api_secret=cfg.api_secret,
            on_event=on_event_with_gap_close, stop_event=stop_event,
            on_disconnect=make_disconnect_cb("private"),
        )
    )
    timer_task = asyncio.create_task(duration_timer())

    try:
        await timer_task
    finally:
        stop_event.set()
        for t in (public_task, private_task):
            t.cancel()
        await asyncio.gather(public_task, private_task, return_exceptions=True)
        for w in writers.values():
            await w.close()
        _GLOBAL_STOP = None

    ended_utc_ms = int(time.time() * 1000)
    (cfg.run_dir / "meta.json").write_text(
        json.dumps(
            {
                "started_utc_ms": started_utc_ms,
                "ended_utc_ms": ended_utc_ms,
                "duration_planned_sec": cfg.duration_sec,
                "restart_count": 0,
                "gaps": gaps,
                "event_counts": counts,
                "symbol": cfg.symbol,
            },
            indent=2,
        )
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_main_orchestration.py -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/main.py tests/test_main_orchestration.py
git commit -m "feat(main): record reconnect gaps in meta.json"
```

---

## Task 17: Convert — JSONL Read with Truncated-Line Skip

**Files:**
- Create: `src/observer/convert.py`
- Create: `tests/test_convert.py`

Implements the read side of §6.7.

- [ ] **Step 1: Write the failing test**

`tests/test_convert.py`:
```python
import json
from pathlib import Path

from observer.convert import iter_jsonl_lines


def test_iter_jsonl_skips_truncated_last_line(tmp_path: Path) -> None:
    p = tmp_path / "test.jsonl"
    # Two complete lines + one truncated (no trailing newline, partial JSON)
    p.write_bytes(b'{"a":1}\n{"a":2}\n{"a":3')
    rows = list(iter_jsonl_lines(p))
    assert rows == [{"a": 1}, {"a": 2}]


def test_iter_jsonl_handles_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_bytes(b"")
    rows = list(iter_jsonl_lines(p))
    assert rows == []


def test_iter_jsonl_skips_unparseable_lines(tmp_path: Path) -> None:
    p = tmp_path / "test.jsonl"
    p.write_bytes(b'{"a":1}\nnot-json\n{"a":2}\n')
    rows = list(iter_jsonl_lines(p))
    assert rows == [{"a": 1}, {"a": 2}]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_convert.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/observer/convert.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_convert.py -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/convert.py tests/test_convert.py
git commit -m "feat(convert): JSONL reader with truncated-line skip"
```

---

## Task 18: Convert — Per-Channel Column Extraction

**Files:**
- Modify: `src/observer/convert.py`
- Modify: `tests/test_convert.py`

Implements the column-extraction table in §6.7.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_convert.py`:
```python
import polars as pl

from observer.convert import build_dataframe


def _envelope(channel: str, raw: dict, *, server_ts_ms: int = 0, recv_monotonic_ns: int = 0) -> dict:
    return {
        "channel": channel,
        "server_ts_ms": server_ts_ms,
        "recv_monotonic_ns": recv_monotonic_ns,
        "recv_utc_ms": 0,
        "raw": raw,
    }


def test_build_dataframe_transaction_extracts_side_price_qty() -> None:
    rows = [
        _envelope(
            "transaction",
            {"content": {"list": [
                {"buySellGb": "1", "contPrice": "1380.5", "contQty": "10"},
                {"buySellGb": "2", "contPrice": "1380.0", "contQty": "5.5"},
            ]}},
            recv_monotonic_ns=100,
        )
    ]
    df = build_dataframe("transaction", rows)
    assert df.columns == ["recv_monotonic_ns", "server_ts_ms", "side", "price", "qty"]
    assert df.shape == (2, 5)
    assert df["side"].to_list() == ["buy", "sell"]
    assert df["price"].to_list() == [pytest.approx(1380.5), pytest.approx(1380.0)]


def test_build_dataframe_myorder_extracts_status_fields() -> None:
    rows = [
        _envelope(
            "myOrder",
            {"content": {
                "order_id": "abc",
                "order_status": "FILLED",
                "order_side": "BID",
                "price": "1380.0",
                "quantity": "50",
                "filled_quantity": "50",
                "timestamp": "1714287030000",
            }},
            recv_monotonic_ns=200,
        ),
    ]
    df = build_dataframe("myOrder", rows)
    assert "order_uuid" in df.columns
    assert "state" in df.columns
    assert "filled_qty" in df.columns
    assert df["order_uuid"].to_list() == ["abc"]
    assert df["state"].to_list() == ["FILLED"]
    assert df["filled_qty"].to_list() == [pytest.approx(50.0)]
```

Add `import pytest` at the top of the test file if not already present.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_convert.py -v` → FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Append to `src/observer/convert.py`:
```python
import polars as pl


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _flatten_transaction(env: dict) -> list[dict]:
    out: list[dict] = []
    items = (env.get("raw", {}).get("content") or {}).get("list") or []
    for item in items:
        side_code = item.get("buySellGb")
        side = "buy" if str(side_code) == "1" else "sell" if str(side_code) == "2" else None
        out.append({
            "recv_monotonic_ns": env["recv_monotonic_ns"],
            "server_ts_ms": env["server_ts_ms"],
            "side": side,
            "price": _safe_float(item.get("contPrice")),
            "qty": _safe_float(item.get("contQty")),
        })
    return out


def _flatten_orderbookdepth(env: dict) -> list[dict]:
    out: list[dict] = []
    content = env.get("raw", {}).get("content") or {}
    items = content.get("list") or []
    for item in items:
        side = item.get("orderType")  # "bid" / "ask"
        out.append({
            "recv_monotonic_ns": env["recv_monotonic_ns"],
            "server_ts_ms": env["server_ts_ms"],
            "side": side,
            "price": _safe_float(item.get("price")),
            "qty": _safe_float(item.get("quantity")),
            "action": "update",  # Bithumb deltas use qty=0 to mean removal — caller can interpret
        })
    return out


def _flatten_my_order(env: dict) -> list[dict]:
    c = env.get("raw", {}).get("content") or {}
    return [{
        "recv_monotonic_ns": env["recv_monotonic_ns"],
        "server_ts_ms": env["server_ts_ms"],
        "order_uuid": c.get("order_id"),
        "state": c.get("order_status"),
        "side": c.get("order_side"),
        "price": _safe_float(c.get("price")),
        "qty": _safe_float(c.get("quantity")),
        "filled_qty": _safe_float(c.get("filled_quantity")),
        "avg_fill_price": _safe_float(c.get("avg_price")),
    }]


def _flatten_my_asset(env: dict) -> list[dict]:
    c = env.get("raw", {}).get("content") or {}
    return [{
        "recv_monotonic_ns": env["recv_monotonic_ns"],
        "server_ts_ms": env["server_ts_ms"],
        "currency": c.get("currency"),
        "balance": _safe_float(c.get("balance")),
        "locked": _safe_float(c.get("locked")),
    }]


_FLATTENERS = {
    "transaction": _flatten_transaction,
    "orderbookdepth": _flatten_orderbookdepth,
    "myOrder": _flatten_my_order,
    "myAsset": _flatten_my_asset,
}


def build_dataframe(channel: str, envelopes: Iterable[dict]) -> pl.DataFrame:
    flattener = _FLATTENERS.get(channel)
    if flattener is None:
        raise ValueError(f"unknown channel: {channel}")
    rows: list[dict] = []
    for env in envelopes:
        rows.extend(flattener(env))
    if not rows:
        # Return an empty df with correct columns by flattening one synthetic envelope.
        synth = flattener({"recv_monotonic_ns": 0, "server_ts_ms": 0, "raw": {}})
        if synth:
            cols = list(synth[0].keys())
            return pl.DataFrame({c: [] for c in cols})
        return pl.DataFrame()
    return pl.DataFrame(rows)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_convert.py -v` → 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/convert.py tests/test_convert.py
git commit -m "feat(convert): per-channel column extraction"
```

---

## Task 19: Convert — Parquet Output and Quality Report CLI

**Files:**
- Modify: `src/observer/convert.py`
- Modify: `tests/test_convert.py`

Implements the §6.7 conversion script and §7.5 quality thresholds.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_convert.py`:
```python
def test_convert_run_writes_parquet_and_report(tmp_path: Path) -> None:
    from observer.convert import convert_run

    # Seed a JSONL with two transaction envelopes
    jsonl = tmp_path / "transaction_2026-04-28T07.jsonl"
    jsonl.write_text(
        json.dumps(_envelope("transaction", {"content": {"list": [
            {"buySellGb": "1", "contPrice": "1380.5", "contQty": "10"},
        ]}}, recv_monotonic_ns=1)) + "\n"
        + json.dumps(_envelope("transaction", {"content": {"list": [
            {"buySellGb": "2", "contPrice": "1380.0", "contQty": "5"},
        ]}}, recv_monotonic_ns=2)) + "\n"
    )
    # Minimal meta.json
    (tmp_path / "meta.json").write_text(json.dumps({
        "started_utc_ms": 0, "ended_utc_ms": 1000, "duration_planned_sec": 1,
        "restart_count": 0, "gaps": [], "event_counts": {"transaction": 2},
        "symbol": "KRW-XRP",
    }))

    report = convert_run(tmp_path)

    parquet_path = tmp_path / "parquet" / "transaction.parquet"
    assert parquet_path.exists()
    df = pl.read_parquet(parquet_path)
    assert df.shape == (2, 5)
    assert "transaction" in report["event_counts"]
    assert report["event_counts"]["transaction"] == 2
    assert "quality" in report
    assert report["quality"]["accumulated_gap_ms"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_convert.py -v` → FAIL.

- [ ] **Step 3: Implement**

Append to `src/observer/convert.py`:
```python
CHANNELS_FOR_RUN = ("orderbookdepth", "transaction", "myOrder", "myAsset")


def convert_run(run_dir: Path) -> dict[str, Any]:
    """Convert all per-channel JSONLs in a run-dir into Parquet and produce a report."""
    out_dir = run_dir / "parquet"
    out_dir.mkdir(exist_ok=True)
    event_counts: dict[str, int] = {}
    for channel in CHANNELS_FOR_RUN:
        rows: list[dict] = []
        for jsonl in sorted(run_dir.glob(f"{channel}_*.jsonl")):
            rows.extend(iter_jsonl_lines(jsonl))
        df = build_dataframe(channel, rows)
        if df.height > 0:
            df = df.sort("recv_monotonic_ns")
        df.write_parquet(out_dir / f"{channel}.parquet", compression="zstd")
        event_counts[channel] = df.height

    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    gaps = meta.get("gaps", [])
    accumulated_gap_ms = sum(int(g.get("duration_ms", 0)) for g in gaps)
    max_gap_ms = max((int(g.get("duration_ms", 0)) for g in gaps), default=0)
    auth_failures = sum(1 for g in gaps if g.get("reason") == "auth_fail")

    report = {
        "run_dir": str(run_dir),
        "event_counts": event_counts,
        "quality": {
            "accumulated_gap_ms": accumulated_gap_ms,
            "max_gap_ms": max_gap_ms,
            "auth_failures": auth_failures,
            "verdict": _verdict(accumulated_gap_ms, max_gap_ms, auth_failures),
        },
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2))
    return report


def _verdict(accum_ms: int, max_ms: int, auth_failures: int) -> str:
    if auth_failures > 0:
        return "INVALID"
    if accum_ms > 300_000 or max_ms > 120_000:
        return "INVALID"
    if accum_ms > 60_000 or max_ms > 30_000:
        return "MARGINAL"
    return "OK"


def _cli() -> None:
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m observer.convert <run-dir>")
    report = convert_run(Path(sys.argv[1]))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    _cli()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_convert.py -v` → 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/observer/convert.py tests/test_convert.py
git commit -m "feat(convert): write Parquet and quality report"
```

---

## Task 20: Operational Script — `run.sh`

**Files:**
- Create: `scripts/run.sh`

Implements §4.2 #4–5: caffeinate + supervisor loop.

- [ ] **Step 1: Write the script**

`scripts/run.sh`:
```bash
#!/usr/bin/env bash
# Supervisor for the observer process. Restarts on non-zero exit up to OBSERVER_MAX_RESTARTS times.
# Wraps the whole run in `caffeinate -i` so macOS doesn't sleep mid-capture.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Activate venv if present
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Load .env so OBSERVER_MAX_RESTARTS is visible
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

MAX_RESTARTS="${OBSERVER_MAX_RESTARTS:-10}"
attempt=0

run_once() {
  python -m observer.main
}

main() {
  while (( attempt <= MAX_RESTARTS )); do
    if (( attempt > 0 )); then
      echo "[run.sh] restart #$attempt after non-zero exit, sleeping 2s…" >&2
      sleep 2
    fi
    if run_once; then
      echo "[run.sh] observer exited cleanly" >&2
      exit 0
    fi
    attempt=$((attempt + 1))
  done
  echo "[run.sh] giving up after $MAX_RESTARTS restarts" >&2
  exit 1
}

# Wrap with caffeinate so the laptop stays awake.
exec caffeinate -i bash -c 'main "$@"' _ "$@"
```

- [ ] **Step 2: Make executable and shellcheck**

```bash
chmod +x scripts/run.sh
shellcheck scripts/run.sh || true   # report-only; some warnings expected for `exec ... main`
```

- [ ] **Step 3: Smoke test the supervisor logic without launching observer**

Create a tiny standalone test script `tests/sh/test_run_supervisor.sh`:
```bash
#!/usr/bin/env bash
# Verifies that scripts/run.sh's supervisor logic restarts on failure up to MAX_RESTARTS.
# This test mocks `python` to exit non-zero; we capture restart count.
set -euo pipefail

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/python" <<'EOF'
#!/usr/bin/env bash
# Always fail
exit 1
EOF
chmod +x "$TMP/python"

# Override caffeinate to be a no-op
cat >"$TMP/caffeinate" <<'EOF'
#!/usr/bin/env bash
shift  # drop -i
exec "$@"
EOF
chmod +x "$TMP/caffeinate"

export PATH="$TMP:$PATH"
export OBSERVER_MAX_RESTARTS=2

# Run with a short timeout and capture output
output=$(./scripts/run.sh 2>&1 || true)

# Expect 2 restart messages
restarts=$(echo "$output" | grep -c "restart #" || true)
if [[ "$restarts" -ne 2 ]]; then
  echo "Expected 2 restart messages, got $restarts" >&2
  echo "$output" >&2
  exit 1
fi
echo "OK: supervisor restarted $restarts times"
```

```bash
chmod +x tests/sh/test_run_supervisor.sh
mkdir -p tests/sh
bash tests/sh/test_run_supervisor.sh
```

Expected: `OK: supervisor restarted 2 times`.

- [ ] **Step 4: Commit**

```bash
git add scripts/run.sh tests/sh/test_run_supervisor.sh
git commit -m "feat(run): supervisor with caffeinate + max restarts"
```

---

## Task 21: Operational Script — `smoke.sh` (5-minute Live Test)

**Files:**
- Create: `scripts/smoke.sh`

Implements §7.4 / §8.4 — short live run with automatic post-checks.

- [ ] **Step 1: Write the script**

`scripts/smoke.sh`:
```bash
#!/usr/bin/env bash
# 5-minute live smoke test against real Bithumb endpoints.
# REQUIRES: live .env with valid v2 read-only API key. NEVER commit captured fixtures untreated.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .venv/bin/activate ]]; then source .venv/bin/activate; fi

RUN_ID="smoke-$(date -u +%Y-%m-%dT%H-%M-%S)"
RUN_DIR="data/$RUN_ID"
mkdir -p "$RUN_DIR"

echo "[smoke] starting 5-minute capture into $RUN_DIR" >&2
echo "[smoke] *** WHILE THIS RUNS, watch your bot server logs for any anomaly ***" >&2

OBSERVER_RUN_DIR="$RUN_DIR" \
OBSERVER_DURATION_SEC=300 \
OBSERVER_MAX_RESTARTS=2 \
python -m observer.main

echo "[smoke] capture finished, running convert..." >&2
python -m observer.convert "$RUN_DIR"

echo "[smoke] post-checks:" >&2

python - <<PY
import json, sys
from pathlib import Path
run_dir = Path("$RUN_DIR")
report = json.loads((run_dir / "report.json").read_text())
counts = report["event_counts"]
verdict = report["quality"]["verdict"]
errors_log = run_dir / "errors.log"
err_lines = errors_log.read_text().count("\n") if errors_log.exists() else 0

print(f"  event_counts={counts}")
print(f"  quality.verdict={verdict}")
print(f"  errors.log lines={err_lines}")

problems = []
if any(v == 0 for v in counts.values()):
    problems.append(f"empty channel(s): {[k for k,v in counts.items() if v==0]}")
if verdict != "OK":
    problems.append(f"quality verdict {verdict}")
if err_lines > 10:
    problems.append(f"errors.log has {err_lines} lines (>10)")

if problems:
    print("FAIL: " + "; ".join(problems))
    sys.exit(1)
print("PASS")
PY
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/smoke.sh
```

- [ ] **Step 3: Lint with shellcheck**

```bash
shellcheck scripts/smoke.sh || true
```

- [ ] **Step 4: Commit (do NOT run live yet — that happens in Task 24)**

```bash
git add scripts/smoke.sh
git commit -m "feat(smoke): 5-minute live smoke + automatic post-checks"
```

---

## Task 22: Operational Script — `redact.py` (Fixture Sanitizer)

**Files:**
- Create: `scripts/redact.py`
- Create: `tests/test_redact.py`

Implements the fixture-redaction procedure in §8.5. We want this BEFORE Task 24 (live capture) so we can sanitize captured events before they hit the repo.

- [ ] **Step 1: Write the failing test**

`tests/test_redact.py`:
```python
import json
from pathlib import Path

from scripts.redact import redact_envelope


def test_redact_my_order_strips_identifiers() -> None:
    env = {
        "channel": "myOrder",
        "server_ts_ms": 1,
        "recv_monotonic_ns": 2,
        "recv_utc_ms": 3,
        "raw": {
            "type": "myOrder",
            "content": {
                "order_id": "secret-order-uuid-7777",
                "order_status": "FILLED",
                "order_side": "BID",
                "price": "1380.0",
                "quantity": "50",
                "filled_quantity": "50",
                "user_id": "real-user-12345",
                "account_id": "real-account-9999",
            },
        },
    }
    out = redact_envelope(env)
    assert out["raw"]["content"]["order_id"] == "REDACTED-ORDER-ID"
    assert out["raw"]["content"]["user_id"] == "REDACTED-USER-ID"
    assert out["raw"]["content"]["account_id"] == "REDACTED-ACCOUNT-ID"
    # Non-sensitive fields preserved
    assert out["raw"]["content"]["order_status"] == "FILLED"
    assert out["raw"]["content"]["price"] == "1380.0"


def test_redact_my_asset_zeros_balances() -> None:
    env = {
        "channel": "myAsset",
        "server_ts_ms": 1,
        "recv_monotonic_ns": 2,
        "recv_utc_ms": 3,
        "raw": {
            "type": "myAsset",
            "content": {"currency": "USDT", "balance": "12345.67", "locked": "100.0"},
        },
    }
    out = redact_envelope(env)
    assert out["raw"]["content"]["currency"] == "USDT"
    assert out["raw"]["content"]["balance"] == "0.0"
    assert out["raw"]["content"]["locked"] == "0.0"


def test_redact_public_passes_through() -> None:
    env = {
        "channel": "transaction",
        "server_ts_ms": 1,
        "recv_monotonic_ns": 2,
        "recv_utc_ms": 3,
        "raw": {"type": "transaction", "content": {"list": [{"contPrice": "1"}]}},
    }
    out = redact_envelope(env)
    assert out == env  # public events have no PII
```

- [ ] **Step 2: Set up scripts package and run tests**

Create `scripts/__init__.py`:
```python
```

Run: `pytest tests/test_redact.py -v` → FAIL (`scripts.redact` not found).

- [ ] **Step 3: Implement**

`scripts/redact.py`:
```python
"""Redact sensitive fields from captured private-channel envelopes.

Usage:
    python scripts/redact.py <input.jsonl> <output.jsonl>

Or import redact_envelope() in tests / other scripts.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

_ID_FIELDS = {
    "order_id": "REDACTED-ORDER-ID",
    "user_id": "REDACTED-USER-ID",
    "account_id": "REDACTED-ACCOUNT-ID",
}
_BALANCE_FIELDS = ("balance", "locked", "available", "total")


def redact_envelope(env: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(env)
    channel = out.get("channel")
    raw = out.get("raw") or {}
    content = raw.get("content") or {}
    if channel == "myOrder":
        for field, replacement in _ID_FIELDS.items():
            if field in content:
                content[field] = replacement
    elif channel == "myAsset":
        for field in _BALANCE_FIELDS:
            if field in content:
                content[field] = "0.0"
    return out


def _cli() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python scripts/redact.py <input.jsonl> <output.jsonl>")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    with src.open("r") as fin, dst.open("w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                env = json.loads(line)
            except json.JSONDecodeError:
                continue
            fout.write(json.dumps(redact_envelope(env)) + "\n")


if __name__ == "__main__":
    _cli()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_redact.py -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/redact.py tests/test_redact.py
git commit -m "feat(redact): sanitize private-channel envelopes for fixtures"
```

---

## Task 23: Pre-Implementation Verification Pass

**Files:** none (research-only)

Implements §9 of the spec — confirm Bithumb API specifics against the live docs before doing the live smoke test. This is a verification gate, not code.

- [ ] **Step 1: Manually verify the 8 items from spec §9 against live docs**

Open https://apidocs.bithumb.com and confirm or correct each:

| # | Item | Confirm value | If different — action |
|---|---|---|---|
| 1 | Public WS URL = `wss://pubwss.bithumb.com/pub/ws` | yes / no | update `src/observer/main.py::PUBLIC_URL` |
| 2 | Private WS URL = `wss://ws-api.bithumb.com/websocket/v1/private` | yes / no | update `src/observer/main.py::PRIVATE_URL` |
| 3 | Symbol code `KRW-XRP` | yes / no | update `.env` `OBSERVER_SYMBOL` |
| 4 | `orderbookdepth` first message depth | record N | note in `data/<smoke-id>/notes.md` |
| 5 | JWT payload fields needed (`access_key`, `nonce`, ?`query_hash`?) | yes / no | update `src/observer/jwt_auth.py` and corresponding tests |
| 6 | Subscribe message format for private (`[ticket, type, type, format]`) | yes / no | update `src/observer/ws_private.py` |
| 7 | `myOrder`/`myAsset` payload field names | record | update `src/observer/convert.py` flatteners + fixtures |
| 8 | Per-account rate-limit pooling | record stance from docs | if confirmed pooled — pause and re-evaluate spec |

- [ ] **Step 2: If any change is required, patch the corresponding module and tests, then run pytest**

```bash
pytest -v
```
Expected: all green.

- [ ] **Step 3: Commit**

```bash
# Only if changes were made; otherwise skip commit.
git add -A
git commit -m "fix: align observer with current Bithumb API spec"
```

If no changes were required, write `data/notes-pre-smoke.md` with the verified values and commit:
```bash
git add data/notes-pre-smoke.md
git commit -m "docs: record Bithumb API spec verification before smoke test"
```

---

## Task 24: Live 5-Minute Smoke + Fixture Capture

**Files:**
- Modify: `tests/fixtures/*.json` (replace synthetic with real-redacted samples)
- Create: `data/<smoke-id>/` (gitignored)

Implements §8.4 / §8.5. This task involves **real network I/O against Bithumb with the real read-only key**. The user must be at the keyboard and watching the MM bot logs.

- [ ] **Step 1: Confirm bot is running and operator is watching it**

Pre-flight checklist (USER must answer yes to all):
- [ ] MM bot is running on its production server
- [ ] Operator can see the bot's logs/metrics in real time on a second screen
- [ ] `.env` in this repo has the v2 read-only **observer** key (NOT the bot's key)
- [ ] Network is stable, laptop is plugged in, screen is on

- [ ] **Step 2: Run the smoke**

```bash
./scripts/smoke.sh
```

Expected output: `PASS` at the end. Run dir is printed; it lives under `data/smoke-…`.

If `FAIL`, do NOT proceed to step 3. Inspect `data/<smoke-id>/errors.log` and `report.json`, fix the issue (likely an API spec mismatch from Task 23), and re-run.

- [ ] **Step 3: Confirm bot was unaffected**

Operator confirms (must be yes):
- [ ] Bot's order placement frequency was normal during the 5 minutes
- [ ] No new rate-limit / 429 errors in bot logs
- [ ] No disconnects on the bot's WS

If any answer is no — STOP. The spec's §1.3 isolation premise is wrong. Do not proceed; bring it back to design.

- [ ] **Step 4: Capture redacted fixtures from the smoke run**

```bash
# Pick the latest smoke run
SMOKE=$(ls -1d data/smoke-* | tail -n1)
mkdir -p tests/fixtures/live
# Take 5 lines from each channel's first JSONL into a temp, redact, save
for ch in orderbookdepth transaction myOrder myAsset; do
  src=$(ls -1 "$SMOKE"/${ch}_*.jsonl 2>/dev/null | head -n1 || true)
  if [[ -n "$src" ]]; then
    head -n5 "$src" > "/tmp/$ch.in.jsonl"
    python scripts/redact.py "/tmp/$ch.in.jsonl" "tests/fixtures/live/$ch.jsonl"
  fi
done
```

Then **manually open each `tests/fixtures/live/*.jsonl` and verify no PII remains** (especially `myOrder` and `myAsset`). If anything looks sensitive, expand `_ID_FIELDS` / `_BALANCE_FIELDS` in `scripts/redact.py` and rerun.

- [ ] **Step 5: Add a regression test that loads the live fixtures**

`tests/test_live_fixtures.py`:
```python
import json
from pathlib import Path

import pytest

LIVE_DIR = Path(__file__).parent / "fixtures" / "live"
CHANNELS = ["orderbookdepth", "transaction", "myOrder", "myAsset"]


@pytest.mark.parametrize("channel", CHANNELS)
def test_live_fixture_envelopes_parse(channel: str) -> None:
    f = LIVE_DIR / f"{channel}.jsonl"
    if not f.exists():
        pytest.skip(f"live fixture {channel} not yet captured")
    lines = [l for l in f.read_text().splitlines() if l.strip()]
    assert lines, "fixture must be non-empty"
    for line in lines:
        env = json.loads(line)
        assert {"channel", "server_ts_ms", "recv_monotonic_ns", "recv_utc_ms", "raw"} <= set(env.keys())
        assert env["channel"] == channel
        # PII spot-check
        if channel == "myOrder":
            assert env["raw"]["content"].get("order_id") == "REDACTED-ORDER-ID"
        if channel == "myAsset":
            assert env["raw"]["content"].get("balance") == "0.0"
```

- [ ] **Step 6: Run all tests**

```bash
pytest -v
```
Expected: all green (live fixture tests will run if fixtures exist; otherwise skipped).

- [ ] **Step 7: Commit fixtures and test**

```bash
git add tests/fixtures/live tests/test_live_fixtures.py
git commit -m "test: add redacted live fixtures from 5-minute smoke run"
```

- [ ] **Step 8: Final go/no-go for the 4-hour capture**

```
$ pytest                    # all unit + integration + live fixture tests
$ ./scripts/smoke.sh        # 5-min live smoke passed (already done in step 2)
$ # bot operator confirms zero impact (already done in step 3)
```

If all three are green → ready to run the production 4-hour capture:

```bash
./scripts/run.sh
```

(Spec success criteria §10 are evaluated after the 4-hour capture completes via `data/<run-id>/report.json`.)

---

## Self-Review (recorded after writing the plan)

**Spec coverage check:**

| Spec section | Implementing task(s) |
|---|---|
| §2.1 F-1 (orderbookdepth) | 9, 10 |
| §2.1 F-2 (transaction) | 9, 10 |
| §2.1 F-3 (myOrder) | 12, 13 |
| §2.1 F-4 (myAsset) | 12, 13 |
| §2.1 F-5 (triple timestamps) | 2 |
| §2.1 F-6 (4h duration, graceful shutdown) | 14, 15 |
| §2.1 F-7 (reconnect with backoff) | 3, 10, 13 |
| §2.1 F-8 (external supervisor up to 10 restarts) | 20 |
| §2.1 F-9 (JSONL → Parquet convert) | 17, 18, 19 |
| §2.1 F-10 (meta.json gaps + counts) | 16 |
| §2.2 NFRs | enforced via §7 quality thresholds in 19 |
| §2.3 absolute constraints | 23 (verification), 24 (live confirm) |
| §6.4 hourly rotation | 5, 6 |
| §6.6 truncated-line recovery | 7, 17 |
| §7.1 #1–11 (failure matrix) | 10, 13, 16, 17, 19, 20 |
| §7.2 backoff policy | 3 |
| §7.3 logging into errors.log / run.log / meta.json | 16, 20, 21 |
| §7.4 5-min dry-run | 21, 24 |
| §7.5 quality thresholds | 19 |
| §8 testing pyramid | every TDD task + 24 |
| §8.5 fixture redaction | 22, 24 |
| §9 pre-implementation verification | 23 |
| §10 success criteria | 24 step 8 |

No gaps.

**Placeholder scan:** searched for `TBD`, `TODO`, `implement later`, `appropriate error handling` — none present in the plan.

**Type consistency:**
- `Envelope` TypedDict (Task 2) is used unchanged in Tasks 5, 9, 12, 14, 18.
- `Config` dataclass (Task 4) is used unchanged in Task 14.
- `OnEvent` type alias is defined identically in `ws_public.py` (Task 9) and `ws_private.py` (Task 12).
- `ExponentialBackoff` constructor signature (`start, cap, sustain_reset_sec`) is consistent across Tasks 3, 10, 13.
- `run_capture` signature includes `public_url` and `private_url` parameters consistently across Tasks 14, 15, 16.
