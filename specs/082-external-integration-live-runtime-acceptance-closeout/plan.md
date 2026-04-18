# Plan：082-external-integration-live-runtime-acceptance-closeout

## 目标

把 external-integration live runtime acceptance 正式落成一张运维验收工单，并把 resident expert replay / session-directory / health 证据链纳入同一条可复现、可审计的 closeout 路径。

## 实施边界

1. 先把当前分支与 `.ai-sdlc` 指针切到 `WI-082`，结束 `WI-081` 已完成后仍被继续复用的状态漂移。
2. 在不改动 resident expert 运行时语义的前提下，扩展 live acceptance runbook 与 docs contract，把 replay / coverage / degraded health 的证据要求写清楚。
3. 跑一组聚焦回归，覆盖 replay materialization、session directory API/adapter 一致性、resident expert stale / restore 语义，以及 smoke harness/doc contract。
4. 只要真实环境变量已经存在，就执行 live smoke bundle 并记录 evidence；如果外部条件不足，按 fail-closed 规则记录 blocker，保持 `WI-082` 继续执行。

## 验证

- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py tests/test_watchdog_external_integration_smoke.py tests/test_watchdog_replay.py tests/test_watchdog_resident_experts.py tests/test_watchdog_session_spine_api.py::test_session_directory_route_surfaces_resident_expert_coverage tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_records_resident_expert_consultation_evidence tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_marks_resident_expert_coverage_degraded_when_stale tests/test_watchdog_ops.py::test_watchdog_ops_alerts_and_healthz_report_degraded_status tests/test_watchdog_ops.py::test_watchdog_ops_exposes_stale_resident_expert_runtime_status tests/integration/test_openclaw_integration_spine.py::test_integration_session_directory_api_and_adapter_share_resident_expert_coverage`
- `set -a; source .env.w; set +a; uv run python scripts/watchdog_external_integration_smoke.py --target health --target feishu --target feishu-control --target provider --target memory --markdown-report artifacts/watchdog-live-acceptance.md`
- `set -a; source .env.w; export WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS="openclaw-codex-watchdog,Ai_AutoSDLC,meeting,portal"; set +a; uv run python scripts/watchdog_external_integration_smoke.py --target feishu-discovery`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
