# Plan：057-task-doc-status-sync

## 目标

把 `WI-057` 收敛为 completed work item task-doc status drift 的 repo-side closeout：修正历史 `tasks.md` 状态文案，并让 repo-local `verify constraints` 能直接拦住类似漂移。

## 实施原则

1. 严格遵循 `ai_sdlc`：先 formalize scope，再写 red tests，再做最小实现，再回写 formal memory。
2. 057 只处理文档状态同步，不修改业务代码。
3. 以 `.ai-sdlc/work-items/<wi>/execution-plan.yaml` 与 `latest-summary.md` 为冻结状态真相，`tasks.md` 只做 mirror 同步。

## 工作流

### Phase 1：冻结 057 formal scope

- 从 completed WI 的 task-doc drift 恢复 057 的正式边界；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/057-*`；
- 固定 057 不修改业务实现与历史执行计划。

### Phase 2：先写 red tests 锁定 completed task-doc status contract

- 写失败测试锁定 completed WI 的 `tasks.md` 不得残留 `进行中/待开始/未开始`；
- 写失败测试锁定 validator 对临时 completed repo 的显式失败信息。

### Phase 3：实现最小 validator 并修正历史 tasks.md 漂移

- 增加 task-doc status drift validator；
- 更新 `WI-030`、`WI-048`、`WI-049` 的 `tasks.md`；
- 接入 `python -m ai_sdlc verify constraints`。

### Phase 4：跑 targeted / smoke 验证

- 运行 targeted tests；
- 运行 repo-local CLI；
- 如外部框架可执行，则复核其真值；若外部工具链自身损坏，则明确记录为外部环境问题。

### Phase 5：完成 formal closeout

- 运行 fresh verification；
- 更新执行日志、summary、checkpoint 与 project-state；
- 明确 `next_work_item_seq=58`。
