# Plan：052-framework-defect-gate-and-path-discipline

## 目标

把 `WI-052` 收敛为 framework defect backlog 的 repo-side closeout：提供仓库内可执行的 `ai_sdlc` 约束入口、canonical formal path classifier，以及覆盖 backlog 缺省和路径漂移的回归测试。

## 实施原则

1. 严格遵循 `ai_sdlc`：先 formalize scope，再写 red tests，再做最小实现，再回写 formal memory。
2. 052 只做 framework contract 与路径纪律，不扩展任何业务功能。
3. 优先复用现有 `watchdog.validation` 模式，把新增逻辑收敛为小而清晰的 validator / CLI wrapper。
4. 约束入口必须在当前仓库内自洽，可直接解释 README 中的命令，而不是隐式依赖站点包。
5. 若外部框架仓库已有同类能力，本 work item 只在本仓库建立兼容真值与回归护栏，不做跨仓库耦合。

## 工作流

### Phase 1：冻结 052 formal scope

- 从 framework defect backlog、README 命令声明与 `WI-051` handoff 恢复 052 的正式边界；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/052-*`；
- 固定 052 不处理 release docs consistency 与业务 backlog。

### Phase 2：先写 red tests 锁定 repo-local CLI 与 canonical checks

- 写失败测试锁定 `python -m ai_sdlc verify constraints` / `status` 的最小行为；
- 写失败测试锁定 backlog 缺省、字段缺失与 `docs/superpowers` formal 误落点；
- 写失败测试锁定 canonical classifier 对 architecture / WI formal / forbidden path 的判断。

### Phase 3：实现最小 validator、classifier 与 CLI wrapper

- 增加 repo-local `ai_sdlc` 最小入口；
- 增加 framework backlog contract validator 与 canonical path classifier；
- 让 CLI 能串起这些检查，并输出稳定结果。

### Phase 4：收敛 repo 文档与 targeted/full 验证

- 修正 repo 中不符合 parser 约束的 framework backlog 记录；
- 更新 README 与相关 formal docs；
- 运行 targeted tests 与 repo-local CLI smoke。

### Phase 5：完成 formal closeout

- 运行 formal 验证集；
- 更新 framework defect backlog、执行日志与 `.ai-sdlc`；
- 明确 WI-052 之后的下一待办入口。

## 风险

- 如果 CLI 入口只在 `uv run pytest` 下可见而不能直接 `python -m ai_sdlc`，README 仍然失真；
- 如果 classifier 设计过度，会把 052 扩大成通用文档管理系统；
- framework backlog 当前已存在 parser 不兼容格式，若不先修正，verify 会持续失败。

## 验收

- 当前仓库根目录可直接执行 repo-local `python -m ai_sdlc verify constraints` 与 `python -m ai_sdlc status`；
- 缺失 canonical framework backlog、字段缺失、formal 文档误落到 `docs/superpowers/*` 都有回归测试；
- `docs/framework-defect-backlog.zh-CN.md` 对 parser 友好，052 覆盖的 defect 已被 formal 消化或标记关闭；
- 052 不引入业务语义改动。
