# Plan：060-memory-advisory-fail-closed-and-ops-hardening

## 目标

把当前脏工作树里的 memory advisory / fail-closed risk gate / ops observability 改动正式收敛成 060 的 canonical owner，并验证它们没有偏离既有稳定 truth。

## 实施原则

1. 先 formalize owner 边界，再跑 targeted verification，再决定是否需要最小修补。
2. 只围绕 memory/risk/ops hardening 这条主题工作，不挪用到别的功能面。
3. 所有 degradation、risk gate 和 ops metrics 都必须消费既有 canonical truth，而不是生成第二套真值。

## 工作流

### Phase 1：冻结 060 owner 边界与 formal docs

- 固定 060 只覆盖 memory advisory / fail-closed / ops hardening；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/060-*`；
- 明确不回改 059 已关闭边界。

### Phase 2：跑 targeted verification 锁定当前 dirty tree

- 运行 memory/risk/ops 对应的 targeted tests；
- 若有失败，只修当前 contract drift。

### Phase 3：完成最小修补与 wiring

- 只修 memory degradation、risk gate、ops metrics/healthz 这条链上的缺口；
- 不做 unrelated refactor。

### Phase 4：跑 targeted / smoke 验证

- 跑目标测试集；
- 跑 repo-local `python -m ai_sdlc verify constraints` 与 `status`。

### Phase 5：完成 formal closeout

- 更新 execution log、summary、checkpoint 与 project-state；
- 仅在 targeted verification 全绿后把 `next_work_item_seq` 推进到 61。
