# Plan：058-post-closeout-residual-backlog-extraction

## 目标

把 `WI-058` 收敛为 post-closeout residual backlog extraction 的 repo-side formal truth layer：冻结 residual 判定边界，产出 canonical ledger/status doc，并让 repo-local `verify constraints` 能阻断后续漂移。

## 实施原则

1. 严格遵循 `ai_sdlc`：先冻结 formal scope，再写 red tests，再做最小实现，再回写 formal memory。
2. 058 只处理 residual truth layer，不修改产品代码。
3. `formal truth` 只来自 `.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/project/config/project-state.yaml` 与相关 `latest-summary.md`；PRD、架构、实施计划只提供候选义务来源。
4. current residual truth 必须只有一个 machine-readable source of truth：`docs/architecture/long-running-residual-backlog-ledger.yaml`。

## 工作流

### Phase 1：冻结 058 owner 边界与输出拓扑

- 固定 058 只做 residual extraction，不做产品实现；
- 冻结 ledger/status doc/validator/test 的目标文件路径；
- 记录 `WI-059` 只可能作为候选 next WI，不在本轮正式切出。

### Phase 2：先写 red tests 锁定 residual backlog contract

- 写失败测试锁定 canonical ledger 与 status doc 的存在约束；
- 写失败测试锁定 ledger item 的 `source_refs` / `formal_truth_refs` 完整性；
- 写失败测试锁定空 ledger + `NO_RESIDUAL_BLOCKERS` 的合法状态。

### Phase 3：实现最小 residual truth layer

- 新建 canonical ledger 与 status doc；
- 新增 residual contract validator；
- 更新 `src/watchdog/validation/__init__.py` 与 `ai_sdlc/cli.py`；
- 保持 validator 只做有限交叉校验，不做全文 obligation mining。

### Phase 4：跑 targeted / smoke 验证

- 运行 targeted tests；
- 运行 repo-local CLI；
- 校验 canonical ledger/status doc 与 `.ai-sdlc` 当前真值一致。

### Phase 5：完成 formal closeout 与后续提名

- 更新 execution log、latest summary、checkpoint 与 project-state；
- 若 residual ledger 非空，再决定是否把 `WI-059` 记录为候选 next WI；
- 若 residual ledger 为空，则固定 `NO_RESIDUAL_BLOCKERS`，且不生成伪待办。
