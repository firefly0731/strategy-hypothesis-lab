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
        symbol="USDT_KRW",
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


@pytest.mark.asyncio
async def test_meta_json_records_gaps_on_reconnect(tmp_path: Path, mock_ws_server) -> None:
    server, port = mock_ws_server
    server.controller.pushes = [{"type": "transaction", "content": {"list": []}}]
    server.controller.drop_after = 1  # close after 1 received frame (a subscribe), forcing reconnect

    cfg = Config(
        api_key="ak", api_secret="sk", run_dir=tmp_path,
        duration_sec=1, max_restarts=1, symbol="USDT_KRW",
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
