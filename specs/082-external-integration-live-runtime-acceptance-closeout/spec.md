# Spec：082-external-integration-live-runtime-acceptance-closeout

## 背景

`WI-080` 已冻结 live acceptance 的 truth boundary，`WI-081` 已把 resident orchestrator 的 recovery / next-step runtime contract 收口到 formal owner 下。当前剩余主风险不再是新增运行时能力，而是 **live runtime acceptance 还没有一张正式工单把外部 smoke bundle 与 resident expert 证据链绑成同一条可审计的验收路径**：

- [`docs/operations/external-integration-live-acceptance.md`](docs/operations/external-integration-live-acceptance.md) 已定义 `health`、`feishu`、`feishu-control`、`feishu-discovery`、`provider`、`memory` 的真实环境验收步骤，但 resident expert 的 replay / session directory / health semantics 仍主要停留在实现与测试层；
- resident expert 相关能力已经具备 repo-local 证据面：audit replay 能 materialize `resident_expert_consultation`，session directory 能暴露 `resident_expert_coverage`，ops health 能在 stale expert 时降级；
- 如果这条证据链不进入 formal owner，后续就可能再次出现“外部集成 smoke 跑了”和“resident expert 监督链真的可复现”被分开叙述的问题，导致 live acceptance 结论无法审计。

因此 `WI-082` 的目标是把 **external-integration live runtime acceptance closeout** 正式建档，并把 resident expert replay / session-directory / health 作为验收证据链的一部分收口；它是运维验收 owner，不是新的产品实现票。

## 范围

### In Scope

- formalize `WI-082` 的 owner、`spec / plan / tasks / task-execution-log` 与 `.ai-sdlc/work-items/082-*` mirror；
- 扩展 live acceptance runbook 与 docs contract，明确 resident expert replay / session-directory / health 是 live runtime acceptance 的必备证据链；
- 运行 targeted repo-local verification，覆盖 replay materialization、session directory 读面一致性、resident expert runtime restore / stale 语义、ops degraded health 语义，以及 live acceptance docs contract；
- 在已有环境配置可用时执行真实环境 smoke bundle，并把 `passed / skipped / blocked` 结果按 fail-closed 规则记录进 evidence bundle；
- 为后续继续执行真实环境 bundle 留下明确的 current task / next action，而不是回填 `WI-081` 或伪装为已完成。

### Out of Scope

- 不新增任何 Watchdog product/runtime feature，也不新增 smoke target；
- 不重开 `WI-080` 的 truth-boundary 设计或 `WI-081` 的 recovery/runtime 语义；
- 不把外部组织安装、域名、证书、密钥轮换、凭证发放写成仓库已经自动完成；
- 不把 `skipped`、缺少 env、provider 未真实命中或 Memory preview route 可调用性写成 live acceptance 已通过。

## Formal Source

- `docs/operations/external-integration-live-acceptance.md`
- `src/watchdog/validation/docs_contracts.py`
- `src/watchdog/validation/external_integration_smoke.py`
- `src/watchdog/services/audit/replay.py`
- `tests/test_long_running_autonomy_doc_contracts.py`
- `tests/test_watchdog_external_integration_smoke.py`
- `tests/test_watchdog_replay.py`
- `tests/test_watchdog_resident_experts.py`
- `tests/test_watchdog_session_spine_api.py`
- `tests/test_watchdog_session_spine_runtime.py`
- `tests/test_watchdog_ops.py`
- `tests/integration/test_openclaw_integration_spine.py`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `.ai-sdlc/project/config/project-state.yaml`

## 非 Owner 约束

- **FR-8201**：`WI-082` 只能做 live runtime acceptance closeout，不得夹带新的产品功能、runtime 语义改造或新的 smoke target。
- **FR-8202**：resident expert 证据链只能作为验收观测面使用；不得借 `WI-082` 修改 resident expert 的行为语义、session-directory contract 或 health degrade 逻辑。
- **FR-8203**：真实环境 smoke 结论必须 fail-closed；任何 `skipped`、`missing_required_env`、`contract_mismatch`、`service_unreachable` 都不得被记录成验收通过。
- **FR-8204**：一旦本轮发现新的 residual blocker，只能按 residual backlog 单独记账，不能混写成 `WI-082` 已闭环。

## 功能需求

- **FR-8205**：live acceptance runbook 与 docs contract 必须显式要求 resident expert replay materialization、session directory coverage 与 stale-expert health semantics 进入 evidence bundle。
- **FR-8206**：targeted verification 必须至少覆盖 `resident_expert_consultation` replay materialization、session directory API 的 `resident_expert_coverage`、API/adapter 读面一致性、resident expert runtime restore / stale 语义，以及 ops summary 的 degraded 状态。
- **FR-8207**：真实环境 smoke bundle 的证据记录必须保留结果摘要，`feishu-control` / `feishu-discovery` 的 `skipped` 只能表示未执行，不能表示已验收。
- **FR-8208**：`WI-082` 活跃期间，`.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/state/resume-pack.yaml`、`.ai-sdlc/project/config/project-state.yaml` 与当前分支必须共同指向 `082-external-integration-live-runtime-acceptance-closeout`，且 `next_work_item_seq` 保持为 `82` 直到工单完成。

## 验证要求

- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py tests/test_watchdog_external_integration_smoke.py tests/test_watchdog_replay.py tests/test_watchdog_resident_experts.py tests/test_watchdog_session_spine_api.py::test_session_directory_route_surfaces_resident_expert_coverage tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_records_resident_expert_consultation_evidence tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_marks_resident_expert_coverage_degraded_when_stale tests/test_watchdog_ops.py::test_watchdog_ops_alerts_and_healthz_report_degraded_status tests/test_watchdog_ops.py::test_watchdog_ops_exposes_stale_resident_expert_runtime_status tests/integration/test_openclaw_integration_spine.py::test_integration_session_directory_api_and_adapter_share_resident_expert_coverage`
- `set -a; source .env.w; set +a; uv run python scripts/watchdog_external_integration_smoke.py --target health --target feishu --target feishu-control --target provider --target memory --markdown-report artifacts/watchdog-live-acceptance.md`
- `set -a; source .env.w; export WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS="openclaw-codex-watchdog,Ai_AutoSDLC,meeting,portal"; set +a; uv run python scripts/watchdog_external_integration_smoke.py --target feishu-discovery`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
