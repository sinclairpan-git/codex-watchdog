# Codex App-Server JSONL Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Codex runtime service Codex bridge with the real `codex app-server` stdio protocol proven during runtime-side deployment.

**Architecture:** Keep the bridge boundary intact, but update the transport to use newline-delimited JSON messages and update startup handshake to send `initialize` with `clientInfo` followed by an `initialized` notification. Lock the regression in focused transport and bridge tests so future deployments cannot silently drift back to the wrong protocol.

**Tech Stack:** Python 3.11, asyncio, pytest, FastAPI service boundary, Codex stdio bridge

---

### Task 1: Record the real protocol contract in regression tests

**Files:**
- Modify: `tests/test_codex_stdio_transport.py`
- Modify: `tests/test_codex_app_server_bridge.py`
- Modify: `tests/test_a_control_agent_control_flow.py`

- [x] **Step 1: Write the failing transport tests**

```python
message = _parse_message(bytes(writer.buffer))
assert message["method"] == "thread/read"
assert writer.buffer.endswith(b"\n")
```

- [x] **Step 2: Write the failing bridge handshake test**

```python
assert transport.calls[0] == (
    "initialize",
    {
        "clientInfo": {"name": "codex-watchdog", "version": "0.1.0"},
        "capabilities": None,
    },
)
assert transport.notifications == [("initialized", {})]
```

- [x] **Step 3: Update test doubles to model notifications**

```python
async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
    self.notifications.append((method, dict(params or {})))
```

- [x] **Step 4: Run the focused bridge tests to confirm red**

Run: `uv run pytest -q tests/test_codex_stdio_transport.py tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py`
Observed: `4 failed, 23 passed` because the production transport still used `Content-Length` framing and the bridge still sent the old initialize handshake.

### Task 2: Fix the transport and bridge to match the deployed runtime

**Files:**
- Modify: `src/a_control_agent/services/codex/protocol.py`
- Modify: `src/a_control_agent/services/codex/stdio_transport.py`
- Modify: `src/a_control_agent/services/codex/app_server_bridge.py`

- [x] **Step 1: Extend the transport protocol with notifications**

```python
async def notify(self, method: str, params: dict[str, Any] | None = None) -> None: ...
```

- [x] **Step 2: Switch stdio framing from `Content-Length` to JSONL**

```python
payload = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
self._writer.write(payload)
```

- [x] **Step 3: Read newline-delimited messages from Codex**

```python
line = await self._reader.readline()
message = json.loads(line.decode("utf-8"))
```

- [x] **Step 4: Send the real startup handshake**

```python
await self._transport.request(
    "initialize",
    {
        "clientInfo": {"name": "codex-watchdog", "version": "0.1.0"},
        "capabilities": None,
    },
)
await self._transport.notify("initialized")
```

- [x] **Step 5: Keep respond/request behavior unchanged for approval callbacks**

Run: `uv run pytest -q tests/test_codex_stdio_transport.py tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py`
Observed: one transport expectation was too strict about empty notification params; after correcting the test to the protocol-minimal shape, the repaired bridge passed.

### Task 3: Verify the repaired contract and operational blast radius

**Files:**
- Modify: `docs/superpowers/plans/2026-04-06-codex-app-server-jsonl-bridge.md`

- [x] **Step 1: Run the adjacent Codex bridge regression suite**

Run: `uv run pytest -q tests/test_codex_stdio_transport.py tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py tests/test_codex_local_client.py`
Observed: `29 passed in 0.48s`

- [x] **Step 2: Mark the plan complete with observed test output**

```markdown
- Result: real Codex app-server handshake now matches deployed runtime (`JSONL`, `initialize(clientInfo)`, `initialized`)
```

- [ ] **Step 3: Commit only the bug-fix scope**

```bash
git add docs/superpowers/plans/2026-04-06-codex-app-server-jsonl-bridge.md \
  src/a_control_agent/services/codex/protocol.py \
  src/a_control_agent/services/codex/stdio_transport.py \
  src/a_control_agent/services/codex/app_server_bridge.py \
  tests/test_codex_stdio_transport.py \
  tests/test_codex_app_server_bridge.py \
  tests/test_a_control_agent_control_flow.py
git commit -m "fix: align codex bridge with app-server protocol"
```
