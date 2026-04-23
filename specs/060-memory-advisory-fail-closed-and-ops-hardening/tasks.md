# 任务分解：060-memory-advisory-fail-closed-and-ops-hardening

> 对应规格：`specs/060-memory-advisory-fail-closed-and-ops-hardening/spec.md`
>
> 对应计划：`specs/060-memory-advisory-fail-closed-and-ops-hardening/plan.md`

## Task 60.1 冻结 060 owner 边界与 formal docs

- **任务编号**：T601
- **状态**：已完成
- **目标**：把 memory advisory / fail-closed / ops hardening 收敛成 060 的 formal truth。

## Task 60.2 跑 targeted verification 锁定当前 dirty tree

- **任务编号**：T602
- **状态**：已完成
- **目标**：先用 targeted tests 暴露 memory/risk/ops 真实 contract drift。

## Task 60.3 完成最小修补与 wiring

- **任务编号**：T603
- **状态**：已完成
- **目标**：只修补当前 targeted verification 暴露出来的稳定 contract 缺口。

## Task 60.4 完成 targeted / smoke 验证

- **任务编号**：T604
- **状态**：已完成
- **目标**：跑通 060 目标测试集与 repo-local smoke gate。

## Task 60.5 完成 060 整体验证并回写 formal memory

- **任务编号**：T605
- **状态**：已完成
- **目标**：关闭 060，并把 closeout 结果正式回写到 `.ai-sdlc`。
