# Spec：079-state-resume-pack-canonical-sync

## 背景

`WI-078` 完成后，repo-local `verify constraints` 已能阻断历史 completed work item 的 review gate mirror drift，但继续做 framework truth 巡检时，又暴露出另一处顶层状态缺口：

- [`.ai-sdlc/state/checkpoint.yml`](/Users/sinclairpan/project/codex-watchdog/.ai-sdlc/state/checkpoint.yml) 已推进到当前 work item；
- 当前执行分支也已不再是旧工单分支；
- 但 [`.ai-sdlc/state/resume-pack.yaml`](/Users/sinclairpan/project/codex-watchdog/.ai-sdlc/state/resume-pack.yaml) 仍长期停留在 `WI-023 / verify / T234` 的工作集快照。

这意味着仓库里仍同时存在两套“当前恢复入口”：

1. checkpoint / active branch 指向当前 work item；
2. 顶层 state resume pack 仍把恢复语义留在历史 work item。

更关键的是，现有 `python -m ai_sdlc verify constraints` 并不会检查这份顶层 state resume pack，因此该漂移可以长期静默存在。

`WI-079` 因此只收口顶层 state resume pack 的 canonical sync 与 repo-local gate，不扩展任何产品运行时、Feishu/Feishu 功能或业务行为。

## 范围

### In Scope

- 明确定义顶层 `.ai-sdlc/state/resume-pack.yaml` 与 active checkpoint / branch 的最小一致性约束；
- 扩展 repo-local reconciliation / constraint gate，使其能识别顶层 state resume pack 漂移；
- 修复当前仓库中顶层 state resume pack 指向历史 `WI-023` 的实际漂移；
- 同步 `WI-079` formal docs、mirror state 与顶层 `.ai-sdlc` 指针。

### Out of Scope

- 不修改任何业务运行时、产品功能或外部集成行为；
- 不重构 `.ai-sdlc/state/resume-pack.yaml` 的 schema，只在既有结构内收口当前真值；
- 不顺带扩展 `ai_sdlc status` 的输出字段；
- 不在本工单中重写 work-item 级 `resume-pack.yaml` 生命周期规则。

## Formal Source

- `ai_sdlc/cli.py`
- `src/watchdog/validation/ai_sdlc_reconciliation.py`
- `tests/test_ai_sdlc_reconciliation.py`
- `tests/test_ai_sdlc_repo_cli.py`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `.ai-sdlc/project/config/project-state.yaml`

## 非 Owner 约束

- **FR-7901**：079 只收口顶层 state resume pack 与 active checkpoint/branch 的真值一致性，不得在本工单中重新设计 `.ai-sdlc` 目录结构。
- **FR-7902**：079 不得把 work-item 级 lifecycle validator 的语义一并扩大到无关文件，只能针对顶层 state resume pack 增补最小 gate。
- **FR-7903**：079 可以同步顶层 state resume pack 到当前 active work item，但不得伪造不存在的执行历史或 task 完成状态。

## 功能需求

- **FR-7904**：repo-local reconciliation inventory 必须能够识别顶层 `.ai-sdlc/state/resume-pack.yaml` 是否仍指向当前 active work item 之外的历史 work item。
- **FR-7905**：当顶层 state resume pack 的 `spec_path`、`plan_path`、`tasks_path`、`current_branch` 或 checkpoint 指针仍指向旧 work item 时，`python -m ai_sdlc verify constraints` 必须明确失败。
- **FR-7906**：顶层 state resume pack 修复必须以“同步到当前 active work item truth”的方式完成，不得删除该文件来规避验证。
- **FR-7907**：active work item 的选择仍继续复用 `collect_reconciliation_inventory()` 的现有 active WI 判定，不得另起一套“当前工单”推断逻辑。
- **FR-7908**：`WI-079` 启动后，`.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/state/resume-pack.yaml` 与当前 branch 必须共同指向 `079-state-resume-pack-canonical-sync`。

## 验证要求

- `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_ai_sdlc_repo_cli.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
