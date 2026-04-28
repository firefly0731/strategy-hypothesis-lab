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
