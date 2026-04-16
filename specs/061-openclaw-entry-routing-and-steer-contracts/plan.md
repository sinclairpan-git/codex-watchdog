# Plan：061-openclaw-entry-routing-and-steer-contracts

## 目标

把 OpenClaw entry routing / steer template / enum contract 这条剩余主题正式收敛为 061 的 canonical owner，并用 targeted verification 证明它已经成立。

## 实施原则

1. 先 formalize owner 边界，再复用已通过的 targeted verification。
2. 只处理入口/模板/枚举 contract，不扩展到新的业务面。
3. 若 targeted verification 已全绿，则以 no-op 修补方式 closeout。

## 工作流

### Phase 1：冻结 061 owner 边界与 formal docs

- 固定 061 只覆盖 openclaw entry routing / steer templates / enum contracts；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/061-*`。

### Phase 2：跑 targeted verification 锁定当前 dirty tree

- 运行 adapter / integration / steer 对应测试；
- 若有失败，再做最小修补。

### Phase 3：完成最小修补与 wiring

- 只修入口/模板/枚举 contract 上的缺口；
- 不做 unrelated refactor。

### Phase 4：跑 targeted / smoke 验证

- 跑目标测试集；
- 跑 repo-local `python -m ai_sdlc verify constraints` 与 `status`。

### Phase 5：完成 formal closeout

- 更新 execution log、summary、checkpoint 与 project-state；
- 仅在 targeted verification 全绿后把 `next_work_item_seq` 推进到 62。
