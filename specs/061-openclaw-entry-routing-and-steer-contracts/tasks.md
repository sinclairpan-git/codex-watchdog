# 任务分解：061-openclaw-entry-routing-and-steer-contracts

> 对应规格：`specs/061-openclaw-entry-routing-and-steer-contracts/spec.md`
>
> 对应计划：`specs/061-openclaw-entry-routing-and-steer-contracts/plan.md`

## Task 61.1 冻结 061 owner 边界与 formal docs

- **任务编号**：T611
- **状态**：已完成
- **目标**：把 openclaw entry routing / steer templates / enum contracts 收敛成 061 的 formal truth。

## Task 61.2 跑 targeted verification 锁定当前 dirty tree

- **任务编号**：T612
- **状态**：已完成
- **目标**：先用 targeted tests 暴露入口/模板/枚举 contract drift。

## Task 61.3 完成最小修补与 wiring

- **任务编号**：T613
- **状态**：已完成
- **目标**：只修补当前 targeted verification 暴露出来的稳定 contract 缺口。

## Task 61.4 完成 targeted / smoke 验证

- **任务编号**：T614
- **状态**：已完成
- **目标**：跑通 061 目标测试集与 repo-local smoke gate。

## Task 61.5 完成 061 整体验证并回写 formal memory

- **任务编号**：T615
- **状态**：已完成
- **目标**：关闭 061，并把 closeout 结果正式回写到 `.ai-sdlc`。
