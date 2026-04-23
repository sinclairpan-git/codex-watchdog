# Plan：062-global-design-provider-memory-closure

## 目标

把原始全局设计中仍未实现的 `OpenAI-compatible Brain provider + durable Memory Hub + session-driven memory ingestion` 闭环正式落地，并以 targeted verification 证明当前服务已经不再只是 contract skeleton。

## 实施原则

1. 先 formalize 当前全局缺口，再用 failing tests 锁定真缺口。
2. 严格遵守 `Session Service` 真源前置、`Memory Hub` advisory-only、provider fail-closed。
3. 先补最小可运行闭环，再保持 preview contract 不升格为 release blocker。

## 工作流

### Phase 1：冻结 062 owner 边界与 formal docs

- 明确 062 只关闭全局设计里仍未落地的 provider runtime / durable memory / ingestion gap；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/062-*`。

### Phase 2：写 failing tests 锁定真实缺口

- provider runtime tests；
- durable memory persistence / ingestion tests；
- hot-path advisory context tests。

### Phase 3：实现 OpenAI-compatible Brain provider

- 新增 provider runtime client；
- 接入 `BrainDecisionService`；
- 把 provider/model 真实反映到 decision metadata。

### Phase 4：实现 durable Memory Hub 与 session-driven ingestion

- 新增 memory store；
- 新增 project register / resident upsert / archive ingest；
- 应用启动 wiring：`Session Service -> Memory Hub`。

### Phase 5：完成 targeted / smoke 验证与 formal closeout

- 运行目标测试集；
- 运行 repo-local constraints / status；
- 回写 `.ai-sdlc` 真值与剩余缺口。
