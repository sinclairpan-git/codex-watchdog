# Plan：054-backlog-id-and-verification-profile-mirror

## 目标

把 `WI-054` 收敛为 backlog 引用 ID 归一化与 verification profile rule mirror 的 repo-side closeout。

## 实施原则

1. 严格遵循 `ai_sdlc`：先 formalize scope，再写 red tests，再做最小实现，再回写 formal memory。
2. 054 只补规则镜像和 validator，不修改业务代码。
3. 优先修正 backlog 标题格式与 rule mirror 缺失，不做额外抽象。

## 工作流

### Phase 1：冻结 054 formal scope

- 从外部框架剩余 blocker 恢复 054 的正式边界；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/054-*`；
- 固定 054 不处理业务或 release docs 扩展。

### Phase 2：先写 red tests 锁定 backlog reference 与 verification profile mirror

- 写失败测试锁定 spec 引用缺失 / 通过两类 backlog reference 场景；
- 写失败测试锁定 verification profile rule 缺失与 drift；
- 观察 repo 在补镜像前的真实失败。

### Phase 3：实现最小 validator 与规则镜像

- 扩展 repo-local validator；
- 新增 `src/ai_sdlc/rules/verification.md`；
- 归一化 framework defect backlog 标题格式。

### Phase 4：跑 targeted / smoke 验证

- 运行 targeted tests；
- 运行 repo-local CLI；
- 使用外部框架真值复核剩余 blocker。

### Phase 5：完成 formal closeout

- 运行 fresh verification；
- 更新执行日志、summary、checkpoint 与 project-state；
- 明确 `next_work_item_seq=55`。
