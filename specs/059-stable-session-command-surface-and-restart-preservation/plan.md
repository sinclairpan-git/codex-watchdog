# Plan：059-stable-session-command-surface-and-restart-preservation

## 目标

把当前脏工作树中的 stable session command surface / restart preservation 改动正式收敛成 059 的 canonical owner，并用 targeted tests 验证这批改动没有偏离既有稳定 contract。

## 实施原则

1. 先 formalize owner 边界，再验证已有改动，再做最小修补。
2. 只围绕当前已经出现的 command/restart/read-surface 变更工作，不趁机扩 scope。
3. 所有 write action 都必须复用 canonical handler / receipt / stable reply，restart 后所有 stable read surfaces 都只读持久化真值。

## 工作流

### Phase 1：冻结 059 owner 边界与 formal docs

- 固定 059 的变更主题为 command surface + restart preservation；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/059-*`；
- 明确不回改 035/048/049/050 的既有 owner。

### Phase 2：跑 targeted red/green verification 锁定当前 dirty tree

- 运行与 command surface / restart preservation 直接相关的 targeted tests；
- 若存在失败，先定位 contract drift，再做最小修补。

### Phase 3：完成最小修补与 wiring

- 只补缺失的 route / transition / receipt / read-surface consistency；
- 不做 unrelated refactor。

### Phase 4：跑 targeted / smoke 验证

- 跑目标测试集；
- 运行 repo-local `python -m ai_sdlc verify constraints`；
- 确认当前 `ai_sdlc status` 与 formal owner 一致。

### Phase 5：完成 formal closeout

- 更新 execution log、summary、checkpoint 与 project-state；
- 只在 targeted verification 全绿后把 `next_work_item_seq` 推进到 60。
