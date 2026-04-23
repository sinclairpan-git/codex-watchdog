# Spec：075-external-integration-smoke-harness-closeout

## 背景

仓库已经通过 `f714d31 feat(smoke): add external integration harness` 落地了外部集成烟测能力，覆盖 `healthz`、Feishu webhook 验证、OpenAI-compatible provider wiring / resident fallback，以及 `Memory Hub` preview cursor smoke path。但 `ai_sdlc` 真值仍停留在 `WI-074`，导致以下分叉同时存在：

- `ai_sdlc status` 仍报告 `linked_wi_id=074-approval-auto-replay-and-canonical-status`；
- `.ai-sdlc/state/checkpoint.yml` 与 `.ai-sdlc/project/config/project-state.yaml` 尚未把外部集成烟测收口为新的 work item；
- `specs/` 与 `.ai-sdlc/work-items/` 缺少与这次实现对应的正式 closeout 工单。

这会让仓库已经完成的能力没有进入框架真值，后续继续推进时会混淆“代码已交付”与“工单未落账”的边界。

## 范围

### In Scope

- 新增 `WI-075` 的 `spec / plan / tasks / task-execution-log`
- 新增 `WI-075` 的 `runtime / execution-plan / resume-pack / latest-summary`
- 更新 `checkpoint` 与 `project-state`，把当前真值切到 `WI-075`
- 保持外部集成烟测实现与文档真值的正式归档关系

### Out of Scope

- 不在本工单内重新修改外部集成烟测代码逻辑
- 不在本工单内新增新的 smoke target、provider 类型或 remote deployment 流程
- 不在本工单内接入真实 Feishu 控制面、真实 OpenAI token 或生产级密钥管理
- 不在本工单内重新打开 `WI-074` 已关闭的审批自动回放问题

## Formal Source

- `docs/architecture/external-integration-smoke-harness-design.md`
- `.ai-sdlc/work-items/074-approval-auto-replay-and-canonical-status/latest-summary.md`
- `scripts/watchdog_external_integration_smoke.py`
- `src/watchdog/validation/external_integration_smoke.py`
- `tests/test_watchdog_external_integration_smoke.py`
- `README.md`
- `docs/getting-started.zh-CN.md`

## 非 Owner 约束

- **FR-7501**：`WI-075` 只做外部集成烟测能力的框架收口，不重新定义实现 owner。
- **FR-7502**：工单真值必须准确镜像已经提交的交付范围，不得借 closeout 工单夹带未实现需求。
- **FR-7503**：`checkpoint`、`project-state`、`runtime`、`resume-pack` 与 `latest-summary` 必须收敛到同一个 `WI-075` 标识和同一个当前分支。

## 功能需求

- **FR-7504**：仓库必须新增 `specs/075-external-integration-smoke-harness-closeout/`，完整记录本次 closeout 的背景、边界与验证口径。
- **FR-7505**：仓库必须新增 `.ai-sdlc/work-items/075-external-integration-smoke-harness-closeout/`，并把 `current_stage` 收口为 `completed`。
- **FR-7506**：`.ai-sdlc/state/checkpoint.yml` 必须把 `linked_wi_id`、`feature.id`、`feature.spec_dir`、`feature.current_branch` 切换到 `WI-075`。
- **FR-7507**：`.ai-sdlc/project/config/project-state.yaml` 必须把 `next_work_item_seq` 前滚到 `76`，避免与已存在的 `WI-075` 冲突。
- **FR-7508**：`latest-summary` 必须明确外部集成烟测实现已经落地，`WI-075` 的职责只是 formal closeout。

## 验证要求

- `uv run pytest -q tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_reconciliation.py`
- `uv run pytest -q`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
