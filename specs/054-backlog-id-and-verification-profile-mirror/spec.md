# Spec：054-backlog-id-and-verification-profile-mirror

## 背景

`WI-053` 完成后，repo-local `verify constraints` 已通过，但按外部 `Ai_AutoSDLC` 的真值仍残留两类 blocker：

1. `specs/052-framework-defect-gate-and-path-discipline/*` 中引用的 `FD-2026-04-05-001`、`FD-2026-04-05-002`、`FD-2026-04-07-003` 没有被外部 backlog breach guard 识别；
2. 缺少 `src/ai_sdlc/rules/verification.md` 这一 verification profile surface。

进一步排查后，根因已明确：

- 当前 `docs/framework-defect-backlog.zh-CN.md` 的标题格式是 `## FD-... 中文标题`，而外部 backlog breach guard 读取时会把整行标题作为 defect id；只有 `## FD-... | 标题` 这类可分割格式才能稳定提取裸 `FD-*`。
- 当前仓库虽已在 `docs/pull-request-checklist.zh.md` 中写入 verification profile token，但缺少与之配对的 `src/ai_sdlc/rules/verification.md`。

`WI-054` 因此只承担这两组 repo-side closeout：规范 backlog 标题格式、补齐 verification rule mirror，并把这两类校验纳入 repo-local gate。

## 范围

### In Scope

- 将 `docs/framework-defect-backlog.zh-CN.md` 的标题归一化为可稳定提取 `FD-*` 的格式；
- repo-local backlog reference validator；
- 新增 `src/ai_sdlc/rules/verification.md`；
- repo-local verification profile validator；
- 针对 backlog reference 与 verification profile 的回归测试；
- 相关 formal docs、`.ai-sdlc` 状态与 closeout 留档。

### Out of Scope

- 新增 framework defect 条目；
- 修改外部 `Ai_AutoSDLC` 仓库；
- 业务代码与 release docs 本身的进一步扩展。

## Formal Source

- `docs/framework-defect-backlog.zh-CN.md`
- `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `### 4.5.3 WI-054：Backlog ID And Verification Profile Mirror`
- 外部框架参考：
  - `Ai_AutoSDLC/src/ai_sdlc/core/backlog_breach_guard.py`
  - `Ai_AutoSDLC/src/ai_sdlc/core/verify_constraints.py`
- `.ai-sdlc/work-items/053-release-entry-docs-consistency/latest-summary.md`
  - `当前下一执行入口固定为 next_work_item_seq=54`

## 非 Owner 约束

- **FR-5401**：054 只关闭 backlog reference 与 verification profile mirror，不新增业务功能。
- **FR-5402**：054 不修改外部框架仓库，只在当前 repo 建立对齐镜像。
- **FR-5403**：054 的新增代码必须可归类为 validator、规则镜像文件或 regression tests。

## 功能需求

- **FR-5404**：framework defect backlog 条目标题必须允许稳定提取裸 `FD-*`；在当前仓库中，`specs/*.md` 引用的 defect id 必须能被 backlog breach guard 识别。
- **FR-5405**：repo-local `verify constraints` 必须覆盖 backlog reference 缺失校验。
- **FR-5406**：仓库必须提供 `src/ai_sdlc/rules/verification.md`，并与 `docs/pull-request-checklist.zh.md` 的 verification profile token 对齐。
- **FR-5407**：repo-local `verify constraints` 必须覆盖 verification profile surface 缺失或 token drift。
- **FR-5408**：054 必须用回归测试覆盖以下场景：
  1. spec 引用不存在的 `FD-*`；
  2. backlog 标题格式正确时，引用校验通过；
  3. 缺失 `src/ai_sdlc/rules/verification.md`；
  4. verification profile token drift；
  5. repo-local CLI 在当前仓库下通过。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。054 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/architecture/coverage-audit-closeout-execution-design.md`
   - `docs/framework-defect-backlog.zh-CN.md`
   - `docs/pull-request-checklist.zh.md`
   - `src/ai_sdlc/rules/verification.md`
   - `specs/054-backlog-id-and-verification-profile-mirror/spec.md`
   - `specs/054-backlog-id-and-verification-profile-mirror/plan.md`
   - `specs/054-backlog-id-and-verification-profile-mirror/tasks.md`
   - `specs/054-backlog-id-and-verification-profile-mirror/task-execution-log.md`
   - `.ai-sdlc/work-items/054-backlog-id-and-verification-profile-mirror/execution-plan.yaml`
   - `.ai-sdlc/work-items/054-backlog-id-and-verification-profile-mirror/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
