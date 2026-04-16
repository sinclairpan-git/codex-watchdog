# 任务分解：056-coverage-audit-snapshot-closeout

> 对应规格：`specs/056-coverage-audit-snapshot-closeout/spec.md`
>
> 对应计划：`specs/056-coverage-audit-snapshot-closeout/plan.md`

## Task 56.1 冻结 056 owner 边界与 formal docs

- **任务编号**：T561
- **状态**：已完成
- **目标**：把 coverage audit snapshot 漂移收敛成 056 的 formal truth。

## Task 56.2 写失败测试锁定 superseded snapshot contract

- **任务编号**：T562
- **状态**：已完成
- **目标**：先用 red tests 锁定旧矩阵标记与 closeout 汇总入口约束。

## Task 56.3 实现最小 validator、文档入口与矩阵标记修复

- **任务编号**：T563
- **状态**：已完成
- **目标**：让旧矩阵不再伪装成当前待办，并把当前 closeout 入口固定下来。

## Task 56.4 完成 targeted / smoke 验证

- **任务编号**：T564
- **状态**：已完成
- **目标**：跑通 repo-local 与外部真值下的 snapshot closeout 验证。

## Task 56.5 完成 056 整体验证并回写 formal memory

- **任务编号**：T565
- **状态**：已完成
- **目标**：关闭 056，并把 coverage audit snapshot closeout 结果正式回写到 `.ai-sdlc`。
