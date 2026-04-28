import asyncio
import json
from datetime import datetime, timezone
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
