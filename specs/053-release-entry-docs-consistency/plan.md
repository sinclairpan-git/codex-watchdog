# Plan：053-release-entry-docs-consistency

## 目标

把 `WI-053` 收敛为 release entry docs consistency 的 repo-side closeout：补齐 `v0.6.0` 固定文档入口，并让 repo-local `verify constraints` 能对齐外部框架的 release docs consistency gate。

## 实施原则

1. 严格遵循 `ai_sdlc`：先 formalize scope，再写 red tests，再做最小实现，再回写 formal memory。
2. 053 只补 entry docs 与 validator，不做发布自动化。
3. 文档内容只覆盖 token contract 与用户入口，不扩张成完整营销或版本公告系统。
4. release docs gate 必须在当前仓库内可执行。

## 工作流

### Phase 1：冻结 053 formal scope

- 从 release docs blocker 与 `WI-052` handoff 恢复 053 的正式边界；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/053-*`；
- 固定 053 不做打包与 artifact 生成。

### Phase 2：先写 red tests 锁定 release docs consistency

- 写失败测试锁定 release docs validator 与 repo-local CLI；
- 写失败测试锁定缺失 entry doc、README drift、release policy / checklist drift；
- 观察 repo 在补文档前的真实失败。

### Phase 3：实现最小 release docs validator 与 repo 文档

- 增加 release docs validator；
- 在 repo-local CLI 中接入该 validator；
- 创建缺失文档并补齐 README 的 entry markers。

### Phase 4：跑 targeted / smoke 验证并修正文档漂移

- 运行 targeted tests；
- 运行 `python -m ai_sdlc verify constraints` smoke；
- 如有 token drift，仅做最小文案修正。

### Phase 5：完成 formal closeout

- 运行 fresh verification；
- 更新执行日志、summary、checkpoint 与 project-state；
- 明确 `next_work_item_seq=54`。

## 风险

- 如果 README 与 release docs token 只是“接近”而非一致，gate 仍会继续报 drift；
- 如果 053 顺手引入离线包生成，会越出当前 owner 边界；
- checklist / policy 需要引用固定路径，若写成自由文案，后续仍容易漂移。

## 验收

- repo-local `verify constraints` 能发现并阻断 release docs consistency drift；
- 仓库具备完整的 `v0.6.0` entry docs；
- 053 不生成真实 artifact，不改业务语义。
