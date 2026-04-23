# Spec：073-ai-sdlc-active-lifecycle-constraint-gate

## 背景

当前仓内存在两个已证实的 framework 缺口：

- `python -m ai_sdlc verify constraints` 的主入口没有接入 `validate_work_item_lifecycle()`，导致 active work item 的 `runtime.yaml` / `resume-pack.yaml` 生命周期失真可能绕过 repo-local 真值校验；
- `tests/test_ai_sdlc_repo_cli.py::test_repo_local_ai_sdlc_status_reports_current_checkpoint` 仍硬编码 `WI-061` 与 `next_work_item_seq=62`，已经与当前 checkpoint 漂移，无法继续作为稳定约束。

这会让 `ai_sdlc` 框架在“状态真值是否真的被主入口强制执行”这件事上留出空窗。

## 范围

### In Scope

- `ai_sdlc/cli.py`
- `tests/test_ai_sdlc_repo_cli.py`
- `ai_sdlc` 工单文档与状态镜像同步

### Out of Scope

- 不在本工单内重写 `watchdog.validation.ai_sdlc_reconciliation` 的生命周期规则本身；
- 不在本工单内补历史所有已关闭 work item 的 metadata 漂移，只对 active work item 的 gate 负责；
- 不在本工单内扩展 `ai_sdlc status` 输出字段范围。

## Formal Source

- `ai_sdlc/cli.py`
- `src/watchdog/validation/ai_sdlc_reconciliation.py`
- `tests/test_ai_sdlc_repo_cli.py`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/project/config/project-state.yaml`

## 非 Owner 约束

- **FR-7301**：073 只把已有生命周期 validator 接回 `ai_sdlc verify constraints` 主入口，不得在本工单内重新定义 approver 规则、batch 规则或 summary 规则。
- **FR-7302**：active work item 的选择必须沿用 `collect_reconciliation_inventory()` 的现有判定结果，禁止另起一套“当前工单”推断逻辑。
- **FR-7303**：仓内 `status` 测试必须改成从 repo 真值动态读取，不得再次写死某个 work item 编号。

## 功能需求

- **FR-7304**：`ai_sdlc verify constraints` 必须对 active work item 执行 `validate_work_item_lifecycle()`，并把 violation 以 `work-item lifecycle (<wi-id>): ...` 形式并入 blocker 输出。
- **FR-7305**：当不存在 active work item 时，`ai_sdlc verify constraints` 行为必须与当前一致，不得引入额外噪音输出。
- **FR-7306**：`tests/test_ai_sdlc_repo_cli.py` 必须显式证明 lifecycle gate 已接入主入口，而不是只测试 validator 单体函数。
- **FR-7307**：repo-local `status` 测试必须根据 `.ai-sdlc/state/checkpoint.yml` 与 `.ai-sdlc/project/config/project-state.yaml` 动态断言 `linked_wi_id`、`current_stage`、`current_branch` 与 `next_work_item_seq`。

## 验证要求

- `uv run pytest -q tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_reconciliation.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
