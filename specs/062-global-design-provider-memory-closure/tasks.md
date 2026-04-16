# 任务分解：062-global-design-provider-memory-closure

> 对应规格：`specs/062-global-design-provider-memory-closure/spec.md`
>
> 对应计划：`specs/062-global-design-provider-memory-closure/plan.md`

## Task 62.1 冻结 062 owner 边界与 formal docs

- **任务编号**：T621
- **状态**：已完成
- **目标**：把全局设计下真实未落地的 provider runtime / durable memory / ingestion gap 固定成 062 的 owner。

## Task 62.2 写 failing tests 锁定 provider runtime 与 durable memory 缺口

- **任务编号**：T622
- **状态**：已完成
- **目标**：让测试先证明外部 provider runtime 和长期记忆持久化当前确实不存在或未闭环。

## Task 62.3 实现 OpenAI-compatible Brain provider

- **任务编号**：T623
- **状态**：已完成
- **目标**：让 `Brain` 支持真实 provider/model/token/base_url 接入，并保留 fail-closed fallback。

## Task 62.4 实现 durable Memory Hub 与 session-driven ingestion

- **任务编号**：T624
- **状态**：已完成
- **目标**：让 `Memory Hub` 具备可跨重启保留的 resident/archive/skills/project 数据，并由 Session 真相驱动沉淀。

## Task 62.5 完成 targeted / smoke 验证并回写 formal memory

- **任务编号**：T625
- **状态**：已完成
- **目标**：验证 062 的代码真值成立，并把结果写回 `.ai-sdlc`。
