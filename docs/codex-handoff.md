# Codex Handoff

## Current Goal

Production hotfix for Watchdog notification spam: stale or nonexistent runtime projects such as `Ai_AutoSDLC` must not be converted into approval prompts, auto-decision notices, or recovery/continue actions.

## AI SDLC Snapshot

- Active git branch: `codex/fix-ai-autosdlc-stale-notifications`
- AI SDLC checkpoint path: `.ai-sdlc/state/checkpoint.yml`
- Top-level resume-pack path: `.ai-sdlc/state/resume-pack.yaml`
- Checkpoint/resume stage: `completed`
- Checkpoint/resume work item: `085-model-first-continuation-governance`
- Checkpoint/resume branch: `codex/reconcile-continuity-runtime`
- Relevant spec: `specs/085-model-first-continuation-governance/spec.md`
- Relevant plan: `specs/085-model-first-continuation-governance/plan.md`
- Relevant tasks: `specs/085-model-first-continuation-governance/tasks.md`

The current hotfix branch intentionally differs from the completed AI SDLC branch recorded in checkpoint/resume. Do not mutate AI SDLC state for this production hotfix unless explicitly directed.

## Current State

- Root cause confirmed: when A-Agent reported a project as missing, Watchdog synthesized a missing-runtime task but carried stale pending approval state into the projection.
- `build_fact_records()` evaluated approval facts before missing-runtime/non-active facts, so stale `pending_approval` data masked `project_not_active` as `approval_state_unavailable`.
- The decision module then acted on the wrong fact and emitted invalid "continue current task" approval/decision notifications.
- Second root cause confirmed: A-Agent can expose multiple native Codex threads under the same project id. Watchdog merged pending approvals by `project_id` only, so old approvals from a previous native thread were applied to the current `Ai_AutoSDLC` native thread.
- The runtime projection now clears approvals for missing runtime tasks and skips local approval merge/workspace activity scanning for those tasks.
- Missing runtime tasks now fail closed immediately as `project_not_active`, regardless of stale pending approval state.
- Active runtime tasks now only merge approvals whose `native_thread_id` / `thread_id` matches the current task's native thread; old cross-thread approvals are ignored.
- Live read root cause confirmed: active `Ai_AutoSDLC` reads can still time out while rebuilding projections from large historical event stores even after the persisted spine is fresh.
- Inactive session read surfaces now use a best-effort persisted fast path for session/progress/facts/pending approvals, so operator/UI reads do not scan session events or touch runtime for non-active projects.
- Inactive persisted reads now drop stale approval projections even if older rows still contain `approval_queue` or stale pending approval counts.
- Empty pending-approval reads now return from persisted spine without scanning events or runtime. Other session read routes build projections in a worker with a bounded timeout and fall back to persisted spine if the expensive projection path stalls.
- Startup non-critical background steps now use a short startup budget, while approval reconciliation remains a startup gate before delivery/orchestrator loops.
- Full local validation is green.
- Production service has been restarted with the hotfix, and a one-shot refresh was run against production data.
- Production `Ai_AutoSDLC` Watchdog API now returns quickly with `pending_approval_count=0` and `approval_queue_len=0`; `pending-approvals` returns count `0`.
- A-Agent still exposes two stale `Ai_AutoSDLC` pending approvals on old native thread `019dcd5c-ed24-7ec3-b1ed-d83623dc3ca4`, while the current active task reports a different native thread and `pending_approval=false`; Watchdog filters those stale approvals out.

## Changed Files

- `src/watchdog/services/session_spine/runtime.py`: missing runtime reconciliation now clears approval state and skips local approval/workspace liveness enrichment.
- `src/watchdog/services/session_spine/runtime.py`: runtime/canonical approval overlays now require matching native thread identity before contributing to the current task projection.
- `src/watchdog/services/session_spine/facts.py`: `runtime_task_missing` now wins before approval fact derivation and returns only `project_not_active`.
- `src/watchdog/services/session_spine/service.py`: persisted `project_not_active` bundles force an empty approval queue and rebuild the session projection with zero pending approvals; approval row thread matching also considers raw `thread_id`.
- `src/watchdog/api/session_spine_queries.py`: session/progress/facts/pending-approvals read routes now share the inactive-project fast path; progress/facts/pending-approvals are async routes; expensive read projection work runs in a worker with timeout fallback to persisted spine.
- `src/watchdog/main.py`: non-critical startup refresh/recover/drain steps have a short timeout budget; approval reconcile keeps the existing guarded startup behavior.
- `tests/test_watchdog_session_spine_api.py`: added coverage proving inactive read surfaces drop stale approvals, empty pending reads avoid event/runtime scans, and existing canonical approval read semantics are preserved.
- `tests/test_watchdog_session_spine_runtime.py`: added regression coverage for missing runtime tasks with stale pending approval state; existing startup tests cover the non-critical startup budget.
- `docs/codex-handoff.md`: updated with the current hotfix state.

## Key Decisions

- Treat A-Agent `NOT_FOUND` / missing runtime task as authoritative for notification safety. Stale local approval state cannot override that.
- Treat native thread identity as part of approval identity. Same `project_id` is not enough to attach a pending approval to the current task.
- Keep the project visible as `blocked` with `project_not_active` for diagnostics, but with an empty approval queue and zero pending approval count.
- Treat inactive project operator reads as diagnostic-only persisted reads, not as an opportunity to reconstruct approval state from old events.
- Treat fresh persisted spine as a safe fallback for read-only UI/operator surfaces when full projection rebuild is too slow.
- Preserve approval reconciliation as a startup gate so delivery/orchestrator loops do not run before stale approvals are reconciled.
- Bound only non-critical startup refresh/drain steps so slow projection work cannot block process startup.

## Commands And Results

- `.venv/bin/python -m pytest -q tests/test_watchdog_session_spine_runtime.py::test_startup_does_not_wait_for_full_delivery_drain tests/test_watchdog_session_spine_runtime.py::test_startup_waits_for_approval_reconcile_before_starting_delivery_loop tests/test_watchdog_session_spine_runtime.py::test_startup_waits_for_approval_reconcile_before_starting_orchestrators tests/test_watchdog_session_spine_runtime.py::test_startup_does_not_start_background_loops_when_reconcile_fails tests/test_watchdog_session_spine_runtime.py::test_startup_does_not_wait_for_initial_orchestrator tests/test_watchdog.py::test_watchdog_startup_continues_when_session_spine_refresh_is_slow` -> `6 passed`
- `.venv/bin/python -m pytest -q tests/test_watchdog_session_spine_runtime.py::test_session_spine_runtime_fail_closes_missing_runtime_task_with_stale_pending_approval_state tests/test_watchdog_session_spine_runtime.py::test_session_spine_runtime_fail_closes_missing_runtime_task_even_with_recent_workspace_activity tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_skips_phantom_approval_when_only_pending_flag_is_set tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_supersedes_stale_pending_approval_after_newer_auto_continue tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_does_not_auto_continue_non_active_project_execution_state tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_does_not_auto_recover_non_active_project_execution_state` -> `6 passed`
- `.venv/bin/python -m pytest -q tests/test_watchdog_session_spine_api.py::test_inactive_persisted_read_surfaces_drop_stale_approval_state_without_event_scan` -> `1 passed`
- `.venv/bin/python -m pytest -q tests/test_watchdog_session_spine_api.py::test_empty_pending_approvals_route_uses_persisted_record_without_event_scan ...` -> `3 passed`
- `.venv/bin/python -m pytest -q tests/test_watchdog_session_spine_runtime.py::test_session_spine_runtime_ignores_pending_approvals_from_stale_native_thread` -> `1 passed`
- `.venv/bin/python -m pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_delivery_worker.py tests/test_watchdog.py tests/test_watchdog_ops.py tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_policy_engine.py` -> `470 passed`
- `.venv/bin/python -m ruff check` -> passed
- `git diff --check` -> passed
- `.venv/bin/python -m pytest -q` -> `1196 passed`
- Production restart: `launchctl kickstart -k gui/502/com.codex.watchdog` -> succeeded
- Production one-shot spine refresh -> `Ai_AutoSDLC` projected as `blocked`, pending `0`, queue `0`, facts `context_critical,recovery_available`
- Watchdog API `/api/v1/watchdog/sessions/Ai_AutoSDLC` -> `success=true`, pending `0`, queue `0`
- Watchdog API `/api/v1/watchdog/sessions/Ai_AutoSDLC/pending-approvals` -> `success=true`, count `0`
- Delivery outbox pending/retrying count -> `0`
- Global persisted spine approval-state scan -> no sessions with pending approval queue/count or `approval_state_unavailable`

## Blockers, Risks, Assumptions

- The local `.venv/bin/pytest` script previously had a stale interpreter path; continue using `.venv/bin/python -m pytest`.
- AI SDLC checkpoint/resume still represent completed WI-085, not this hotfix branch.
- Do not record or paste runtime secrets from `.env.a`, `.env.w`, Keychain, or shell output.

## Exact Next Steps

1. Commit the hotfix.
2. Push `codex/fix-ai-autosdlc-stale-notifications`.
3. Open a PR, request `@codex review`, monitor checks/review, address any issues, and merge to `main`.
