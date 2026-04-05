from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from a_control_agent.services.codex.stdio_transport import StdioJsonRpcTransport


class FakeWriter:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _parse_frame(raw: bytes) -> dict[str, Any]:
    headers, body = raw.split(b"\r\n\r\n", 1)
    assert headers.startswith(b"Content-Length: ")
    return json.loads(body.decode("utf-8"))


def _encode_frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


@pytest.mark.asyncio
async def test_stdio_transport_sends_framed_request_and_resolves_response() -> None:
    reader = asyncio.StreamReader()
    writer = FakeWriter()
    transport = StdioJsonRpcTransport(reader=reader, writer=writer)

    await transport.start()
    pending = asyncio.create_task(transport.request("thread/read", {"threadId": "thr_live"}))
    await asyncio.sleep(0)

    message = _parse_frame(bytes(writer.buffer))
    assert message["method"] == "thread/read"
    assert message["params"] == {"threadId": "thr_live"}
    assert isinstance(message["id"], int)

    reader.feed_data(_encode_frame({"id": message["id"], "result": {"thread": {"id": "thr_live"}}}))
    result = await pending
    await transport.stop()

    assert result == {"thread": {"id": "thr_live"}}
    assert writer.closed is True


@pytest.mark.asyncio
async def test_stdio_transport_dispatches_server_requests_to_handler() -> None:
    reader = asyncio.StreamReader()
    writer = FakeWriter()
    seen: list[dict[str, Any]] = []

    async def on_server_request(message: dict[str, Any]) -> None:
        seen.append(message)

    transport = StdioJsonRpcTransport(reader=reader, writer=writer, server_request_handler=on_server_request)
    await transport.start()

    reader.feed_data(
        _encode_frame(
            {
                "id": "req_123",
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": "thr_live", "command": "curl https://example.com"},
            }
        )
    )
    await asyncio.sleep(0)
    await transport.stop()

    assert len(seen) == 1
    assert seen[0]["method"] == "item/commandExecution/requestApproval"
    assert writer.buffer == b""
