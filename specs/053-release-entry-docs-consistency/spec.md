# Spec：053-release-entry-docs-consistency

## 背景

`WI-052` 已完成 project backlog 与 framework defect backlog 之后的 repo-side closeout，当前 `next_work_item_seq=53` 对应的剩余 formal blocker 不再是业务功能，而是 release entry docs consistency。

按外部 `Ai_AutoSDLC` 的固定约束，当前仓库若出现以下任一 release entry surface，就必须保持整组 `v0.6.0` 文档入口对齐：

- `README.md`
- `docs/releases/v0.6.0.md`
- `USER_GUIDE.zh-CN.md`
- `packaging/offline/README.md`
- `docs/框架自迭代开发与发布约定.md`
- `docs/pull-request-checklist.zh.md`

本仓库此前已暴露出这组 blocker：缺少 release notes、user guide、offline README、release policy 与 PR checklist，同时 README 也未提供对应 `v0.6.0` 离线包与 release notes 入口。

`WI-053` 因此只承担 release entry docs consistency 的 repo-side closeout：补齐固定文档入口、把这些文档的 token 契约纳入 repo-local `python -m ai_sdlc verify constraints`，并为其建立回归测试。

## 范围

### In Scope

- `README.md` 的 `v0.6.0` release entry 文案补齐；
- 新增 `docs/releases/v0.6.0.md`、`USER_GUIDE.zh-CN.md`、`packaging/offline/README.md`、`docs/框架自迭代开发与发布约定.md`、`docs/pull-request-checklist.zh.md`；
- repo-local release docs consistency validator；
- 针对缺失 entry doc、README drift、release policy / checklist drift 的回归测试；
- 相关 formal docs、`.ai-sdlc` 状态与 closeout 留档。

### Out of Scope

- 实际离线包生成、发布自动化或 artifact 上传；
- 版本号升级到 `v0.6.1+`；
- 业务功能、runtime semantics、Feishu / Watchdog / Codex runtime service 代码行为；
- release pipeline 之外的 broader documentation rewrite。

## Formal Source

- `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `### 4.5.2 WI-053：Release Entry Docs Consistency`
- `README.md`
  - `## AI-SDLC`
- 外部框架约束参考：
  - `Ai_AutoSDLC/src/ai_sdlc/core/verify_constraints.py` 中 `RELEASE_DOCS_CONSISTENCY_SURFACES`
- `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/latest-summary.md`
  - `当前下一执行入口固定为 next_work_item_seq=53`

## 非 Owner 约束

- **FR-5301**：053 只关闭 release entry docs consistency，不生成真实离线包。
- **FR-5302**：053 只补文档入口与 validator，不修改业务代码语义。
- **FR-5303**：053 的新增代码必须可归类为 doc validator、CLI gate 或 regression tests。

## 功能需求

- **FR-5304**：repo-local `python -m ai_sdlc verify constraints` 必须覆盖 release docs consistency。
- **FR-5305**：当 release entry docs 中任一固定文件缺失时，校验必须明确失败并指出缺失路径。
- **FR-5306**：当 `README.md`、release notes、user guide、offline README、release policy、PR checklist 中任一 required token 漂移时，校验必须明确失败。
- **FR-5307**：仓库必须补齐以下固定 entry docs，并满足 `v0.6.0` token 约束：
  1. `docs/releases/v0.6.0.md`
  2. `USER_GUIDE.zh-CN.md`
  3. `packaging/offline/README.md`
  4. `docs/框架自迭代开发与发布约定.md`
  5. `docs/pull-request-checklist.zh.md`
- **FR-5308**：053 必须用回归测试覆盖以下场景：
  1. 缺失 release entry doc；
  2. README 缺少 `v0.6.0` / release note / offline bundle marker；
  3. release policy / checklist token drift；
  4. repo-local CLI 在当前仓库下对齐后通过。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。053 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/architecture/coverage-audit-closeout-execution-design.md`
   - `README.md`
   - `docs/releases/v0.6.0.md`
   - `USER_GUIDE.zh-CN.md`
   - `packaging/offline/README.md`
   - `docs/框架自迭代开发与发布约定.md`
   - `docs/pull-request-checklist.zh.md`
   - `specs/053-release-entry-docs-consistency/spec.md`
   - `specs/053-release-entry-docs-consistency/plan.md`
   - `specs/053-release-entry-docs-consistency/tasks.md`
   - `specs/053-release-entry-docs-consistency/task-execution-log.md`
   - `.ai-sdlc/work-items/053-release-entry-docs-consistency/execution-plan.yaml`
   - `.ai-sdlc/work-items/053-release-entry-docs-consistency/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。

## 用户故事

### 用户故事 1：维护者需要固定 release entry docs

作为维护者，我需要仓库内的 release entry docs 有固定入口，这样 README、release notes、user guide、offline README、policy 与 checklist 不会彼此漂移。

### 用户故事 2：仓库内校验必须能直接发现 release docs drift

作为维护者，我需要在当前仓库里运行 `python -m ai_sdlc verify constraints` 时就能发现 release docs drift，而不是依赖外部工作区。
