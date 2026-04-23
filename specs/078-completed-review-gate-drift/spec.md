# Spec：078-completed-review-gate-drift

## 背景

`WI-077` 关闭后，repo-local canonical backlog、residual ledger 与 `specs/*/tasks.md` 已全部收口，但继续做 repo-wide drift scan 时，发现另一类 formal state 漂移仍然存在：

- 多个已完成的历史 work item 在 `.ai-sdlc/work-items/<wi>/runtime.yaml` 与 `resume-pack.yaml` 中仍保留 `review_approval_status: pending`；
- 这些 work item 的 `current_stage` 已为 `completed`，`latest-summary.md` 也已宣称完成；
- `validate_work_item_lifecycle()` 本身会把 `review_approval_status != approved` 视为违规，但 `python -m ai_sdlc verify constraints` 目前只校验 active/highest work item，因此历史 completed mirror drift 被绕过。

这会导致 repo 内同时存在两套互相冲突的 formal truth：

1. 历史 work item 已完成并允许被后续工单接续；
2. 同一 work item 的 review gate 元数据仍停留在 `pending`，像是从未正式收口。

`WI-078` 因此只关闭 completed work item review gate mirror drift，不引入新的业务功能，也不伪造不存在的历史审批结论。

## 范围

### In Scope

- 定义 completed work item review gate drift contract；
- 扩展 repo-local `ai_sdlc verify constraints`，使其覆盖 completed work item 的 review gate mirror drift；
- 修复当前仓库中已确认受影响的历史 `.ai-sdlc/work-items/*/{runtime,resume-pack}.yaml` 元数据；
- 为上述行为补齐回归测试与 formal closeout 文档。

### Out of Scope

- 不修改任何业务运行时、产品功能或 Feishu/Feishu 行为；
- 不伪造历史 reviewer 名单，不把缺失审计证据的旧工单强行改写成 `approved`；
- 不重写历史 `latest-summary.md`、`execution-plan.yaml` 的任务结果；
- 不把非 completed work item 的 review gate 语义一并重构。

## Formal Source

- `ai_sdlc/cli.py`
- `src/watchdog/validation/ai_sdlc_reconciliation.py`
- `tests/test_ai_sdlc_repo_cli.py`
- `tests/test_ai_sdlc_reconciliation.py`
- `.ai-sdlc/work-items/049-feishu-entrypoint-closure/runtime.yaml`
- `.ai-sdlc/work-items/049-feishu-entrypoint-closure/resume-pack.yaml`
- `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/runtime.yaml`
- `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/resume-pack.yaml`
- `.ai-sdlc/work-items/051-high-coupling-test-hardening/runtime.yaml`
- `.ai-sdlc/work-items/051-high-coupling-test-hardening/resume-pack.yaml`
- `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/runtime.yaml`
- `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/resume-pack.yaml`
- `.ai-sdlc/work-items/053-release-entry-docs-consistency/runtime.yaml`
- `.ai-sdlc/work-items/053-release-entry-docs-consistency/resume-pack.yaml`
- `.ai-sdlc/work-items/054-backlog-id-and-verification-profile-mirror/runtime.yaml`
- `.ai-sdlc/work-items/054-backlog-id-and-verification-profile-mirror/resume-pack.yaml`
- `.ai-sdlc/work-items/055-checkpoint-string-compatibility/runtime.yaml`
- `.ai-sdlc/work-items/055-checkpoint-string-compatibility/resume-pack.yaml`
- `.ai-sdlc/work-items/056-coverage-audit-snapshot-closeout/runtime.yaml`
- `.ai-sdlc/work-items/056-coverage-audit-snapshot-closeout/resume-pack.yaml`
- `.ai-sdlc/work-items/057-task-doc-status-sync/runtime.yaml`
- `.ai-sdlc/work-items/057-task-doc-status-sync/resume-pack.yaml`
- `.ai-sdlc/work-items/058-post-closeout-residual-backlog-extraction/runtime.yaml`
- `.ai-sdlc/work-items/058-post-closeout-residual-backlog-extraction/resume-pack.yaml`
- `.ai-sdlc/work-items/059-stable-session-command-surface-and-restart-preservation/runtime.yaml`
- `.ai-sdlc/work-items/059-stable-session-command-surface-and-restart-preservation/resume-pack.yaml`
- `.ai-sdlc/work-items/060-memory-advisory-fail-closed-and-ops-hardening/runtime.yaml`
- `.ai-sdlc/work-items/060-memory-advisory-fail-closed-and-ops-hardening/resume-pack.yaml`
- `.ai-sdlc/work-items/061-entry-routing-and-steer-contracts/runtime.yaml`
- `.ai-sdlc/work-items/061-entry-routing-and-steer-contracts/resume-pack.yaml`
- `.ai-sdlc/work-items/062-global-design-provider-memory-closure/runtime.yaml`
- `.ai-sdlc/work-items/062-global-design-provider-memory-closure/resume-pack.yaml`
- `.ai-sdlc/work-items/063-async-memory-ingest-sink/runtime.yaml`
- `.ai-sdlc/work-items/063-async-memory-ingest-sink/resume-pack.yaml`
- `.ai-sdlc/work-items/064-feishu-direct-delivery-runtime/runtime.yaml`
- `.ai-sdlc/work-items/064-feishu-direct-delivery-runtime/resume-pack.yaml`

## 非 Owner 约束

- **FR-7801**：078 只关闭 completed work item review gate mirror drift，不回改业务执行结果。
- **FR-7802**：078 不得在缺少审计证据时，把历史 `pending` review metadata 伪造成 `approved`。
- **FR-7803**：078 可以移除悬空的 legacy review gate 字段，但不得改写 `execution-plan.yaml`、`latest-summary.md` 或 task closeout 事实。

## 功能需求

- **FR-7804**：repo-local `python -m ai_sdlc verify constraints` 必须能识别 completed work item 的 review gate mirror drift，而不只依赖 active/highest work item。
- **FR-7805**：若某个 completed work item 的 `runtime.yaml` 或 `resume-pack.yaml` 仍声明 `review_approval_status: pending`，repo-local validator 必须明确失败。
- **FR-7806**：对于当前仓库中缺少 reviewer 证据、但悬空保留了 `review_approval_status: pending` 与空 `review_approved_by` 的历史 completed work items，078 必须以“删除悬空字段”的方式修复漂移，而不是回填伪造 reviewer。
- **FR-7807**：active/in-progress work item 的 lifecycle 校验语义不得因 078 而放宽；当前 active WI 仍继续复用既有 `validate_work_item_lifecycle()` 约束。
- **FR-7808**：078 至少要覆盖当前已确认漂移的 completed work items：`WI-049` 至 `WI-064` 中实际仍残留 `review_approval_status: pending` 的条目。

## 验证要求

- `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_ai_sdlc_repo_cli.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
