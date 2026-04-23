# Plan：056-coverage-audit-snapshot-closeout

## 目标

把 `WI-056` 收敛为 coverage audit historical snapshot 的 repo-side closeout：给旧矩阵加 superseded 标记，补一个当前 closeout 汇总入口，并让 repo-local `verify constraints` 能直接拦住这类漂移。

## 实施原则

1. 严格遵循 `ai_sdlc`：先 formalize scope，再写 red tests，再做最小实现，再回写 formal memory。
2. 056 只处理“旧审计快照误导当前状态”的文档与规则面，不重开产品功能。
3. 保留 `2026-04-14` 矩阵作为历史输入，但必须明确降级，不允许继续被读作 live todo。

## 工作流

### Phase 1：冻结 056 formal scope

- 从当前 `NO_BLOCKERS` 与旧矩阵残留“未落地”冲突恢复 056 的正式边界；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/056-*`；
- 固定 056 不修改 owner ledger、不重开 048-055 语义。

### Phase 2：先写 red tests 锁定 snapshot closeout contract

- 写失败测试锁定历史矩阵必须带 superseded 标记；
- 写失败测试锁定当前 closeout 汇总入口必须存在；
- 写失败测试锁定 repo-local validator 能发现缺失。

### Phase 3：实现最小 validator 与文档入口修复

- 增加 coverage audit snapshot contract validator；
- 更新 `coverage-audit-matrix.md` 为历史快照；
- 新增 current closeout 汇总文档；
- 接入 `python -m ai_sdlc verify constraints`。

### Phase 4：跑 targeted / smoke 验证

- 运行 targeted tests；
- 运行 repo-local CLI；
- 复核外部 `Ai_AutoSDLC` 真值仍为 `NO_BLOCKERS`。

### Phase 5：完成 formal closeout

- 运行 fresh verification；
- 更新执行日志、summary、checkpoint 与 project-state；
- 明确 `next_work_item_seq=57`。
