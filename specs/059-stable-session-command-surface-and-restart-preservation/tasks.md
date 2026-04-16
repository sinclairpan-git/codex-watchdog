# 任务分解：059-stable-session-command-surface-and-restart-preservation

> 对应规格：`specs/059-stable-session-command-surface-and-restart-preservation/spec.md`
>
> 对应计划：`specs/059-stable-session-command-surface-and-restart-preservation/plan.md`

## Task 59.1 冻结 059 owner 边界与 formal docs

- **任务编号**：T591
- **状态**：已完成
- **目标**：把 stable session command surface / restart preservation 收敛成 059 的 formal truth。

## Task 59.2 跑 targeted verification 锁定当前 dirty tree

- **任务编号**：T592
- **状态**：已完成
- **目标**：先用 targeted tests 暴露 command surface / restart preservation 的真实 contract drift。

## Task 59.3 完成最小修补与 wiring

- **任务编号**：T593
- **状态**：已完成
- **目标**：只修补当前 targeted verification 暴露出来的稳定 contract 缺口。

## Task 59.4 完成 targeted / smoke 验证

- **任务编号**：T594
- **状态**：已完成
- **目标**：跑通 059 目标测试集与 repo-local smoke gate。

## Task 59.5 完成 059 整体验证并回写 formal memory

- **任务编号**：T595
- **状态**：已完成
- **目标**：关闭 059，并把 closeout 结果正式回写到 `.ai-sdlc`。
