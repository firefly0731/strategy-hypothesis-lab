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
        symbol="USDT_KRW",
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
