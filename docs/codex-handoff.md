# Codex Handoff

## Current Goal

Fix production notification spam where stale/nonexistent Codex tasks such as `Codex`/`SInclairPan`/old native sessions can still be synchronized into Watchdog and pushed to Feishu.

## AI SDLC Snapshot

- Active branch: `codex/reconcile-continuity-runtime`
- Checkpoint path: `.ai-sdlc/state/checkpoint.yml`
- Top-level resume pack path: `.ai-sdlc/state/resume-pack.yaml`
- Constitution path: `.ai-sdlc/memory/constitution.md`
- Optional IDE guidance: `.cursor/rules/ai-sdlc.md`
- Referenced work item: `085-model-first-continuation-governance`
- Spec path: `specs/085-model-first-continuation-governance/spec.md`
- Plan path: `specs/085-model-first-continuation-governance/plan.md`
- Tasks path: `specs/085-model-first-continuation-governance/tasks.md`
- Checkpoint now says stage `completed`, feature current branch `codex/reconcile-continuity-runtime`.
- Top-level resume pack now says `current_stage: completed`, `current_batch: 8`, `current_branch: codex/reconcile-continuity-runtime`.
- WI-085 runtime and work-item resume pack also now use `current_branch: codex/reconcile-continuity-runtime`.
- `specs/085-model-first-continuation-governance/tasks.md` has T851-T858 checked complete.

## Current State

- The AI SDLC checkpoint/resume-pack mismatch has been intentionally reconciled after user approval.
- The current working tree contains meaningful code/test changes unrelated to the already-completed WI-085 task list, plus new continuity docs/scripts.
- Targeted tests for the touched runtime/client/delivery/orchestrator areas are passing.
- Full test suite passed when run outside the sandbox; the sandboxed run only failed because two tests invoke `uv run python` and need access to the normal uv cache.
- `uv run pytest` currently fails to spawn `pytest` because the generated console script points at an old path. Use `.venv/bin/python -m pytest ...` in this workspace unless the venv is rebuilt.
- MiniMax provider live smoke passed on 2026-05-03 with the configured `.env.w` provider settings after running outside the filesystem sandbox so macOS Keychain and external network access were available.
- Provider live smoke returned `provider_intent=propose_execute`, `probe_mode=live`, model `MiniMax-M2.7`, provider `openai-compatible`, and fallback provider `resident_orchestrator`.
- Decision action validity was rechecked with targeted provider/policy/action tests: provider output normalization, canonical continuation decisions, policy mapping, and action execution paths are green.
- Current production-spam fix is in progress on top of the existing dirty branch. Root causes found:
  - A-agent `/api/v1/tasks/{project_id}` could still return stale native tasks after active native sync found no current Codex threads.
  - Old/legacy native records had no source marker, so active-only list filtering did not protect all project lookup paths.
  - Local Codex discovery could derive invalid project names from case-variant home directories and Codex internal state directories.
  - Delivery worker still allowed project-level notifications when the session spine record was missing, so stale outbox records could reach Feishu.
- Additional production gaps found during restart/live verification:
  - Missing runtime tasks could be revived by recent workspace mtime; they now fail closed as `project_not_active` and do not scan workspace activity.
  - Watchdog startup could block indefinitely on startup refresh/reconcile/memory drains; startup steps now have a bounded budget and continue with background loops.
  - `/healthz` could block on full ops summary/event scans; it now returns a bounded degraded fallback with `health_error=summary_timeout`.
  - Inactive persisted session reads could block behind store locks or expensive projections; single session reads now have an async/best-effort fast path for `project_not_active` records.
- Production runtime verification after restart:
  - A-Agent returns `NOT_FOUND` for `Codex`, `sinclairpan`, `ICP`, and `Ai_AutoSDLC`; `codex-watchdog` remains visible as `native_codex`.
  - Watchdog persisted spine marks `Codex`, `sinclairpan`, and `ICP` as `blocked` with `project_not_active`.
  - Watchdog delivery outbox has no `pending` or `retrying` records.
  - Watchdog `/healthz` is reachable but currently degraded via `health_error=summary_timeout`, indicating ops summary/event scans still need follow-up performance work.

## Changed Files

- `AGENTS.md`: added repository-level Codex continuity protocol that treats AI SDLC state as framework truth and `docs/codex-handoff.md` as a bridge.
- `docs/codex-handoff.md`: updated this handoff with the resumed task context, verification, and next steps.
- `.ai-sdlc/state/checkpoint.yml`: reconciled WI-085 to `current_stage: completed`, branch `codex/reconcile-continuity-runtime`, updated sync timestamps.
- `.ai-sdlc/state/resume-pack.yaml`: reconciled top-level resume pack branch/timestamp/checkpoint fingerprint to match checkpoint.
- `.ai-sdlc/work-items/085-model-first-continuation-governance/runtime.yaml`: reconciled current branch and timestamp.
- `.ai-sdlc/work-items/085-model-first-continuation-governance/resume-pack.yaml`: reconciled current branch/timestamp/checkpoint fingerprint to match checkpoint.
- `bin/start-a-agent.sh`: starts uvicorn through `python -m uvicorn`.
- `bin/start-a-public-tunnel.sh`: added cloudflared tunnel helper for A-agent on port 8710.
- `bin/start-watchdog-public-tunnel.sh`: added cloudflared tunnel helper for watchdog on port 8720.
- `src/a_control_agent/services/codex/client.py`: prevents fallback to all Codex threads when active workspace roots are empty.
- `src/a_control_agent/services/codex/client.py`: additionally rejects case-variant home directories, Codex internal directories, `.codex`, `codex`, and the local home username as derived project ids.
- `src/a_control_agent/storage/tasks_store.py`: records task source (`manual`, `native_codex`, `legacy`), hides inactive/stale native records from active task listing and project lookup once `active_native_thread_ids` exists, while keeping by-thread diagnostic lookup available.
- `src/watchdog/services/delivery/worker.py`: suppresses project-level approval, approval-result, decision-result, and progress-summary envelopes when the session spine project record is missing or inactive; portfolio directory summaries remain exempt.
- `src/watchdog/services/session_spine/runtime.py`: missing runtime tasks no longer consult workspace activity before fail-closing.
- `src/watchdog/services/session_spine/task_state.py`: `runtime_task_missing` now always derives a paused/non-active project state.
- `src/watchdog/services/session_spine/service.py`: inactive persisted records return through a fast persisted read path without rebuilding expensive recovery/goal/decision projections.
- `src/watchdog/services/session_spine/store.py`: added best-effort lock-free persisted lookup for inactive diagnostic reads.
- `src/watchdog/api/session_spine_queries.py`: single session read route and trivial dependencies are async, and inactive records use the best-effort fast path.
- `src/watchdog/api/deps.py`: token dependency is async to avoid threadpool starvation for async routes.
- `src/watchdog/main.py`: startup background steps and `/healthz` now have bounded timeouts with degraded fallback instead of blocking process startup/probes.
- `src/watchdog/services/brain/provider_runtime.py`: canonicalizes continuation decision aliases and rejects non-canonical continuation decisions.
- `src/watchdog/services/brain/service.py`: exposes decision context for evidence capture.
- `src/watchdog/services/delivery/worker.py`: normalizes semantic fact signatures for duplicate suppression and keeps observe-only block notices sticky-suppressed.
- `src/watchdog/services/session_spine/orchestrator.py`: records full decision context in policy decision evidence.
- `tests/test_codex_local_client.py`: covers empty active workspace filtering.
- `tests/test_a_control_agent.py`: covers stale native project lookup after empty active sync.
- `tests/test_codex_local_client.py`: covers case-variant home cwd and Codex internal cwd rejection.
- `tests/test_watchdog_brain_provider_runtime.py`: covers approval alias mapping and invalid continuation decisions.
- `tests/test_watchdog_delivery_worker.py`: covers timestamp-insensitive duplicate fact suppression and sticky suppression after the normal window.
- `tests/test_watchdog_delivery_worker.py`: covers missing-project suppression for decision notifications, approvals, and progress summaries.
- `tests/test_watchdog_session_spine_runtime.py`: covers full decision context evidence recording.
- `tests/test_watchdog_session_spine_runtime.py`: covers missing-runtime-task fail-closed behavior even when workspace activity exists.
- `tests/test_watchdog.py`: covers Watchdog startup continuing when session spine refresh is slow.
- `tests/test_watchdog_ops.py`: covers `/healthz` timeout fallback.
- `docs/codex-handoff.md`: recorded the 2026-05-03 MiniMax live provider smoke and decision action validation results.
- `docs/codex-handoff.md`: recorded the production spam root causes, fixes, and verification.

## Key Decisions And Rationale

- Reconcile AI SDLC truth only after explicit user instruction; this was done in the current turn.
- Trust the working tree for local code progress, but do not assume these changes belong to completed WI-085.
- Validate with targeted tests first, then broader checks.
- Use `.venv/bin/python -m pytest` and `.venv/bin/python -m ruff` because project console scripts still contain stale shebangs.
- Do not record provider tokens or Feishu credentials in handoff notes; record only redacted smoke evidence and status.
- Stale native task visibility is fail-closed: once active native sync has an `active_native_thread_ids` view, only those active ids plus explicit manual tasks are visible through the project/list APIs. Legacy native-looking records remain available by thread id for diagnostics but cannot be rediscovered by Watchdog via project lookup.
- Project-level delivery is fail-closed on missing session spine records. This intentionally changes the prior behavior that allowed `decision_result` notifications through without a current session record; this is the right production posture for suppressing nonexistent-task spam.
- Runtime-missing project liveness is fail-closed even when the old workspace path has fresh filesystem activity. Filesystem mtime is not authoritative evidence that a Codex task still exists.
- Startup and health checks now prefer bounded degraded service over blocking the process. The richer ops summary remains available through ops surfaces, but liveness must stay cheap enough for production.

## Commands And Results

- `git status --short`: showed modified runtime/test files plus new `AGENTS.md`, tunnel helpers, and `docs/codex-handoff.md`.
- `sed -n ... .ai-sdlc/state/checkpoint.yml`: checkpoint says WI-085 stage `execute`, branch `main`.
- `sed -n ... .ai-sdlc/state/resume-pack.yaml`: resume pack says WI-085 completed on branch `codex/085-model-first-continuation-governance`.
- `sed -n ... specs/085-model-first-continuation-governance/tasks.md`: T851-T858 are checked complete.
- `git switch -c codex/reconcile-continuity-runtime`: moved dirty working tree from `main` to a Codex work branch.
- `shasum -a 256 .ai-sdlc/state/checkpoint.yml`: generated reconciled checkpoint fingerprint `cb9185c0fd2db1bf4bbb1799b5bcad580a8f4d69076351bb4d0dc93ffebfae21`.
- `uv run pytest -q ...`: failed to spawn `pytest` due environment/script issue.
- `uv sync --dev`: completed after escalation, but existing console scripts still point at an old virtualenv path.
- `.venv/bin/python -m pytest -q tests/test_codex_local_client.py tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_session_spine_runtime.py`: `231 passed in 9.89s`.
- `.venv/bin/python -m ruff check`: passed.
- `.venv/bin/python -m pytest -q`: sandboxed run reached `1182 passed, 2 failed`; both failures were release-gate tests whose subprocess `uv run python ...` could not access `/Users/sinclairpan/.cache/uv`.
- `.venv/bin/python -m pytest -q` with escalated permissions: `1184 passed in 36.86s`.
- `.venv/bin/python -m ai_sdlc verify constraints`: `Constraints OK`.
- Reconciliation inventory check: `active_work_item_id=085-model-first-continuation-governance`, `next_work_item_seq=86`, `stale_pointers=[]`.
- `.venv/bin/python -m ruff check`: passed after SDLC reconciliation.
- `.venv/bin/python -m pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_codex_local_client.py tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_session_spine_runtime.py`: `247 passed in 9.65s`.
- `.venv/bin/python -m pytest -q` with escalated permissions after SDLC reconciliation: `1184 passed in 37.44s`.
- `git status --short`: clean at start of the 2026-05-03 decision-module check.
- `.venv/bin/python -m pytest -q tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_policy_engine.py tests/test_watchdog_action_execution.py`: `87 passed in 2.46s`.
- `.venv/bin/python -m dotenv -f .env.w list`: confirmed provider env entries are parseable; do not paste this output because it includes sensitive non-provider runtime values.
- `security find-generic-password -s watchdog.brain-provider.minimax -a default` inside sandbox: item lookup failed, causing provider smoke to report missing `brain_provider_api_key`.
- `env WATCHDOG_SMOKE_PROVIDER_LIVE=true .venv/bin/python -m dotenv -f .env.w run -- .venv/bin/python scripts/watchdog_external_integration_smoke.py --target provider` with escalated permissions: provider check `passed`, reason `ok`, `probe_mode=live`, model `MiniMax-M2.7`, provider intent `propose_execute`, fallback provider `resident_orchestrator`.
- `jq ... .data/watchdog/session_spine.json` and `jq ... .data/watchdog/delivery_outbox.json`: local stores are empty; no local pending spam records were available to clean.
- `.venv/bin/python -m pytest -q tests/test_a_control_agent.py::test_project_lookup_hides_stale_native_thread_after_empty_active_sync tests/test_codex_local_client.py::test_local_codex_client_rejects_case_variant_home_directory_as_project_id tests/test_codex_local_client.py::test_local_codex_client_rejects_codex_internal_directory_as_project_id tests/test_watchdog_session_spine_runtime.py::test_session_spine_runtime_fail_closes_missing_runtime_task_even_with_recent_workspace_activity`: initially `3 failed, 1 passed`, confirming the stale lookup/name derivation defects.
- Same targeted command after fixes plus active native visibility smoke: `5 passed in 0.51s`.
- `.venv/bin/python -m pytest -q tests/test_watchdog_delivery_worker.py::test_delivery_worker_suppresses_decision_notification_when_project_record_is_missing tests/test_watchdog_delivery_worker.py::test_delivery_worker_suppresses_approval_when_project_record_is_missing tests/test_watchdog_delivery_worker.py::test_delivery_worker_suppresses_progress_summary_when_project_record_is_missing tests/test_watchdog_delivery_worker.py::test_delivery_worker_suppresses_approval_for_inactive_project_without_downstream_call tests/test_watchdog_delivery_worker.py::test_delivery_worker_suppresses_decision_notification_for_inactive_project_without_downstream_call`: `5 passed in 0.35s`.
- `.venv/bin/python -m pytest -q tests/test_a_control_agent.py tests/test_a_control_agent_sync_loop.py tests/test_codex_local_client.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_session_spine_runtime.py`: `227 passed in 8.92s`.
- `.venv/bin/python -m ruff check src/a_control_agent/services/codex/client.py src/a_control_agent/storage/tasks_store.py src/watchdog/services/delivery/worker.py tests/test_a_control_agent.py tests/test_codex_local_client.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_session_spine_runtime.py`: passed.
- `.venv/bin/python -m pytest -q`: `1190 passed in 37.91s`.
- `.venv/bin/python -m ruff check`: passed.
- Restarted `com.codex.a-control-agent` and `com.codex.watchdog` with `launchctl kickstart -k`.
- A-Agent `/healthz`: `status=ok`, `tracked_threads=598`, `tracked_projects=14`.
- A-Agent project lookup after restart: `Codex`, `sinclairpan`, `ICP`, and `Ai_AutoSDLC` returned `NOT_FOUND`; `codex-watchdog` returned a visible `native_codex` task.
- Watchdog persisted session spine after refresh: `Codex`, `sinclairpan`, and `ICP` are `blocked` with `project_not_active`.
- Watchdog delivery outbox pending/retrying query: no records.
- Watchdog `/healthz`: reachable and returns degraded fallback `health_error=summary_timeout`.
- Watchdog single session route via curl: `Codex`, `sinclairpan`, `ICP`, and `codex-watchdog` returned HTTP 200; each currently reports `blocked` with `project_not_active` in the persisted spine.
- `.venv/bin/python -m pytest -q`: `1192 passed in 36.17s`.
- `.venv/bin/python -m ruff check`: passed.
- `git diff --check`: passed.

## Blockers, Risks, Assumptions

- AI SDLC checkpoint/resume-pack mismatch is reconciled and verified in the working tree, pending commit.
- The `.venv/bin/pytest` script has a stale interpreter path; direct module invocation works.
- Sandbox cannot read the configured Keychain item; live provider verification requires escalated execution or a runtime environment with normal Keychain access.
- The MiniMax token itself is usable in the normal escalated runtime, as verified by live provider smoke.
- Full test suite passed after the production-spam and startup/health hardening fixes.
- Production still has historical stale records on disk for diagnostics, but A-Agent project/list lookup hides them and Watchdog spine marks known stale projects as non-active.
- Watchdog health is reachable but degraded because full ops summary/event scans are still timing out under current production data/lock pressure. This no longer blocks process startup or liveness checks, but it remains a performance follow-up.
- `codex-watchdog` is currently marked `project_not_active` by Watchdog because the AI SDLC project state is completed, even though A-Agent sees active native Codex threads. This blocks autonomous continuation and delivery for that project; decide separately whether completed SDLC state should suppress the current maintenance thread.
- Do not revert pre-existing user changes unless explicitly requested.

## Exact Next Steps

1. Investigate why full Watchdog ops summary still times out on production data/locks, then restore `/healthz` to a normal `ok`/real-summary result instead of timeout fallback.
2. Decide whether `codex-watchdog` should be considered active while AI SDLC state says completed; if yes, adjust authoritative project-state reconciliation for maintenance sessions.
3. Keep using `.venv/bin/python -m pytest` because `.venv/bin/pytest` still has a stale shebang.
