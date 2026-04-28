import asyncio
import json

import pytest
import websockets


@pytest.mark.asyncio
async def test_mock_ws_echoes(mock_ws_server) -> None:
    """The mock server echoes back any text frame the client sends."""
    server, port = mock_ws_server
    server.controller.script = [{"echo": True}]
    async with websockets.connect(f"ws://localhost:{port}") as ws:
        await ws.send(json.dumps({"hello": "world"}))
        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
    assert json.loads(msg) == {"hello": "world"}
