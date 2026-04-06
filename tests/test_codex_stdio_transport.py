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


def _parse_message(raw: bytes) -> dict[str, Any]:
    assert raw.endswith(b"\n")
    return json.loads(raw.decode("utf-8").strip())


def _encode_message(message: dict[str, Any]) -> bytes:
    return json.dumps(message).encode("utf-8") + b"\n"


@pytest.mark.asyncio
async def test_stdio_transport_sends_jsonl_request_and_resolves_response() -> None:
    reader = asyncio.StreamReader()
    writer = FakeWriter()
    transport = StdioJsonRpcTransport(reader=reader, writer=writer)

    await transport.start()
    pending = asyncio.create_task(transport.request("thread/read", {"threadId": "thr_live"}))
    await asyncio.sleep(0)

    message = _parse_message(bytes(writer.buffer))
    assert message["method"] == "thread/read"
    assert message["params"] == {"threadId": "thr_live"}
    assert isinstance(message["id"], int)

    reader.feed_data(_encode_message({"id": message["id"], "result": {"thread": {"id": "thr_live"}}}))
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
        _encode_message(
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


@pytest.mark.asyncio
async def test_stdio_transport_reads_large_jsonl_response_frame() -> None:
    reader = asyncio.StreamReader()
    writer = FakeWriter()
    transport = StdioJsonRpcTransport(
        reader=reader,
        writer=writer,
        request_timeout_seconds=0.1,
    )

    await transport.start()
    pending = asyncio.create_task(transport.request("thread/read", {"threadId": "thr_live"}))
    await asyncio.sleep(0)

    message = _parse_message(bytes(writer.buffer))
    large_payload = "x" * 80_000
    reader.feed_data(
        _encode_message(
            {
                "id": message["id"],
                "result": {
                    "thread": {
                        "id": "thr_live",
                        "turns": [{"id": "turn_1", "text": large_payload}],
                    }
                },
            }
        )
    )
    result = await pending
    await transport.stop()

    assert result["thread"]["turns"][0]["text"] == large_payload


@pytest.mark.asyncio
async def test_stdio_transport_sends_jsonl_notification_without_request_id() -> None:
    reader = asyncio.StreamReader()
    writer = FakeWriter()
    transport = StdioJsonRpcTransport(reader=reader, writer=writer)

    await transport.start()
    await transport.notify("initialized")
    await transport.stop()

    message = _parse_message(bytes(writer.buffer))
    assert message == {"method": "initialized"}
