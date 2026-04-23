# 任务分解：057-task-doc-status-sync

> 对应规格：`specs/057-task-doc-status-sync/spec.md`
>
> 对应计划：`specs/057-task-doc-status-sync/plan.md`

## Task 57.1 冻结 057 owner 边界与 formal docs

- **任务编号**：T571
- **状态**：已完成
- **目标**：把 completed WI 的 task-doc status drift 收敛成 057 的 formal truth。

## Task 57.2 写失败测试锁定 completed task-doc status contract

- **任务编号**：T572
- **状态**：已完成
- **目标**：先用 red tests 锁定 `tasks.md` 与 completed lifecycle 的同步约束。

## Task 57.3 实现最小 validator 并修正历史 tasks.md 漂移

- **任务编号**：T573
- **状态**：已完成
- **目标**：让 completed WI 的 `tasks.md` 与冻结执行结果一致。

## Task 57.4 完成 targeted / smoke 验证

- **任务编号**：T574
- **状态**：已完成
- **目标**：跑通 repo-local task-doc drift 验证。

## Task 57.5 完成 057 整体验证并回写 formal memory

- **任务编号**：T575
- **状态**：已完成
- **目标**：关闭 057，并把 task-doc status drift closeout 结果正式回写到 `.ai-sdlc`。
