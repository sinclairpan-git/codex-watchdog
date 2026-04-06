from __future__ import annotations

import asyncio
import json
import shlex
from contextlib import suppress
from typing import Any, Awaitable, Callable


ServerRequestHandler = Callable[[dict[str, Any]], Awaitable[None]]


class StdioJsonRpcTransport:
    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: Any,
        server_request_handler: ServerRequestHandler | None = None,
        request_timeout_seconds: float = 10.0,
        close_hook: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._server_request_handler = server_request_handler
        self._request_timeout_seconds = request_timeout_seconds
        self._close_hook = close_hook
        self._started = False
        self._next_id = 0
        self._pending: dict[str | int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        reader_task = self._reader_task
        if reader_task is not None:
            reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await reader_task
        self._writer.close()
        wait_closed = getattr(self._writer, "wait_closed", None)
        if callable(wait_closed):
            await wait_closed()
        if self._close_hook is not None:
            await self._close_hook()
        self._fail_pending(RuntimeError("transport stopped"))

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_started()
        self._next_id += 1
        request_id = self._next_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self._send({"id": request_id, "method": method, "params": dict(params or {})})
        try:
            return await asyncio.wait_for(future, timeout=self._request_timeout_seconds)
        finally:
            self._pending.pop(request_id, None)

    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None:
        self._ensure_started()
        await self._send({"id": request_id, "result": dict(result)})

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._ensure_started()
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = dict(params)
        await self._send(message)

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("transport not started")

    async def _send(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        self._writer.write(payload)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    return
                raw = line.decode("utf-8").strip()
                if not raw:
                    continue
                message = json.loads(raw)
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except asyncio.IncompleteReadError:
            return

    async def _handle_message(self, message: dict[str, Any]) -> None:
        if "method" in message and "id" in message:
            if self._server_request_handler is not None:
                await self._server_request_handler(message)
            return
        request_id = message.get("id")
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        if "error" in message:
            future.set_exception(RuntimeError(str(message["error"])))
            return
        result = message.get("result")
        if isinstance(result, dict):
            future.set_result(result)
        else:
            future.set_result({})

    def _fail_pending(self, exc: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()


class SubprocessCodexTransport:
    def __init__(
        self,
        *,
        command: str | list[str],
        server_request_handler: ServerRequestHandler | None = None,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        self._command = shlex.split(command) if isinstance(command, str) else list(command)
        self._server_request_handler = server_request_handler
        self._request_timeout_seconds = request_timeout_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._transport: StdioJsonRpcTransport | None = None

    async def start(self) -> None:
        if self._transport is not None:
            await self._transport.start()
            return
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("failed to open stdio pipes for codex app-server")
        self._transport = StdioJsonRpcTransport(
            reader=self._process.stdout,
            writer=self._process.stdin,
            server_request_handler=self._server_request_handler,
            request_timeout_seconds=self._request_timeout_seconds,
            close_hook=self._close_process,
        )
        await self._transport.start()

    async def stop(self) -> None:
        if self._transport is None:
            return
        await self._transport.stop()
        self._transport = None

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._transport is None:
            raise RuntimeError("transport not started")
        return await self._transport.request(method, params)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self._transport is None:
            raise RuntimeError("transport not started")
        await self._transport.notify(method, params)

    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None:
        if self._transport is None:
            raise RuntimeError("transport not started")
        await self._transport.respond(request_id, result)

    async def _close_process(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
