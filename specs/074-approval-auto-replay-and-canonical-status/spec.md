# Spec: 074 Approval Auto Replay And Canonical Status

## Background

WI-074 closes a regression at the AI SDLC approval boundary. The risk classifier was over-failing workspace-local test commands and safe file permission requests, which broke approval auto-replay, callback recovery, and bridge-level expectations. In parallel, one sync-loop assertion was still checking the legacy `waiting_human` output shape instead of the canonical state model required by WI-066.

The fix must remain inside the formal contract:

- Local, workspace-contained test execution can be auto-approved.
- Safe file permissions can be auto-approved.
- Network, credentials, system, release, and boundary-escape operations remain fail-closed.
- Externally emitted task state stays canonical even when legacy aliases are accepted on input.

## Scope

In scope:

- Update `src/a_control_agent/risk/classifier.py` to classify explicit local pytest invocations and safe `permissions:fs.*` requests correctly.
- Keep fail-closed handling for unsafe permission scopes and non-local operations.
- Update regression tests for risk classification and sync-loop canonical output.
- Record the work item inside `specs/074-*` and `.ai-sdlc/work-items/074-*`.

Out of scope:

- Broadening auto-approval to arbitrary shell commands.
- Reworking approval persistence or bridge protocols.
- Changing canonical task states beyond the already-specified WI-066 contract.

## Formal Sources

- `codex-watchdog-prd.md` section 7.1
- `specs/066-task-state-model-closure/spec.md`
- `specs/067-risk-boundary-and-control-observability/spec.md`

## Requirements

### FR-7401 Local Pytest Auto-Approval

The risk classifier must classify explicitly local pytest invocations as auto-approvable when they stay within the workspace boundary and do not request path-escape behavior. Supported forms include:

- `pytest -q`
- `uv run pytest -q`
- `python3 -m pytest -q`

These commands must not require human approval.

### FR-7402 Safe File Permissions

The risk classifier must classify `permissions:fs.read` and `permissions:fs.write` combinations as safe auto-approvable permissions. Unknown permissions must remain non-auto-approved.

### FR-7403 Fail-Closed High-Risk Permissions

`permissions:network.*`, `permissions:credentials.*`, malformed permission requests, and unknown permission scopes must remain fail-closed and must not become auto-approved through this work item.

### FR-7404 Canonical Approval Status Output

When the system receives a pending-approval alias such as `waiting_human`, externally emitted state must still normalize to the canonical output:

- `status = waiting_for_approval`
- `phase = planning`

### FR-7405 Replay Regression Coverage

Regression coverage must prove that approval replay and callback handling succeed once low-risk commands and safe file permissions are classified correctly.

## Verification

- `uv run ruff check src/a_control_agent/risk/classifier.py tests/test_m3_risk.py tests/test_a_control_agent_sync_loop.py`
- `uv run pytest -q tests/test_m3_risk.py tests/test_m3_agent_approvals.py tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py tests/test_a_control_agent_sync_loop.py`
- `uv run pytest -q`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
