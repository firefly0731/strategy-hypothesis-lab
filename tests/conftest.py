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
