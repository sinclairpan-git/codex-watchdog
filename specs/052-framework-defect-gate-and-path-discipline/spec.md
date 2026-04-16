# Spec：052-framework-defect-gate-and-path-discipline

## 背景

`WI-051` 已正式关闭项目 backlog 中最后一个显式业务待办，当前剩余的 formal owner 已不再是产品功能，而是 repo 侧尚未完全机器化的 framework contract。

当前仓库仍保留三条高风险 framework defect：

1. `FD-2026-04-05-001`：用户明确要求“先文档、禁止直接 coding、不要写到 superpowers”后，执行链仍可能绕过仓库 canonical 文档真值；
2. `FD-2026-04-05-002`：framework backlog 的 canonical 发现与缺省校验不稳定；
3. `FD-2026-04-07-003`：已知 canonical 文档目录存在时，仍可能把正式落点回退到 `docs/superpowers/*`。

此外，仓库 README 声称可直接执行 `python -m ai_sdlc verify constraints`，但在当前 repo 自身环境下，`uv run python -m ai_sdlc verify constraints` 还无法找到本地模块，说明约束入口仍依赖外部环境而非仓库真值。

`WI-052` 因此只承担 framework defect backlog 与 canonical path discipline 的 repo-side closeout：把约束入口、路径分类和回归测试固定到当前仓库中。

## 范围

### In Scope

- `FD-2026-04-05-001`、`FD-2026-04-05-002`、`FD-2026-04-07-003` 的 repo-side formal closeout；
- repo-local `python -m ai_sdlc verify constraints` / `status` 最小可执行入口；
- framework backlog 存在性、字段完备性、canonical formal path 分类与禁止目录检查；
- 针对“缺少 canonical backlog”“formal 文档误落到 docs/superpowers”“已知 canonical 目录存在时路径分类漂移”的回归测试；
- 相关 formal docs、README 与 `.ai-sdlc` 状态同步。

### Out of Scope

- `Ai_AutoSDLC` 外部框架仓库本体修改；
- release docs consistency / packaging blocker；
- 任何 watchdog / a-control 的业务运行时语义；
- 新的产品 backlog、入口定义或高耦合功能增强。

## Formal Source

- `docs/framework-defect-backlog.zh-CN.md`
  - `## FD-2026-04-05-001 宿主执行链未在用户明确要求后回切到仓库文档先行真值`
  - `## FD-2026-04-05-002 Framework backlog 发现与缺省校验存在漏斗`
  - `## FD-2026-04-07-003 已知 canonical 文档路径存在时仍回退到 skill 默认 spec 目录`
- `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `### 4.5.1 WI-052：Framework Defect Gate And Path Discipline`
- `README.md`
  - `## AI-SDLC`
- `.ai-sdlc/work-items/051-high-coupling-test-hardening/latest-summary.md`
  - `当前下一执行入口固定为 WI-052`

## 非 Owner 约束

- **FR-5201**：052 只关闭 framework contract、canonical path discipline 与 repo-local constraint entry，不关闭任何业务功能条款。
- **FR-5202**：052 不修改外部 `Ai_AutoSDLC` 仓库；若发现外部实现差异，只允许在本仓库建立兼容入口或回归护栏。
- **FR-5203**：052 的所有新增代码必须可归类为 validator、path classifier、CLI wrapper 或 regression tests。

## 功能需求

- **FR-5204**：仓库必须提供 repo-local `python -m ai_sdlc verify constraints` 最小入口，在当前仓库根目录直接执行即可运行本地约束校验，而不是依赖站点包或外部工作区。
- **FR-5205**：当仓库已初始化（存在 `.ai-sdlc/project/config/project-state.yaml`）但缺失 `docs/framework-defect-backlog.zh-CN.md` 时，约束校验必须明确失败并指出 canonical 路径。
- **FR-5206**：framework defect backlog 的每个 `FD-*` 条目必须具备最小必填字段；字段缺失或格式不被 parser 接受时，约束校验必须明确失败。
- **FR-5207**：仓库必须提供 formal 文档 canonical path classifier，至少能区分：
  1. 跨 work item 总设计 -> `docs/architecture/*.md`
  2. 单 work item formal `spec/plan/tasks` -> `specs/<WI>/<artifact>.md`
  3. `docs/superpowers/*` 只能作为辅助过程产物，不得被 classifier 识别为正式落点
- **FR-5208**：若仓库已存在 `docs/architecture/` 与 `specs/`，且候选 formal 路径落在 `docs/superpowers/*`，约束校验必须明确失败并给出 canonical 期望。
- **FR-5209**：052 必须用回归测试覆盖以下场景：
  1. 缺失 canonical framework backlog；
  2. backlog 条目字段不完整；
  3. formal `spec/plan/tasks` 路径误落到 `docs/superpowers/*`；
  4. repo-local CLI 能在当前仓库下跑通 `verify constraints` 与 `status`。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。052 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/architecture/coverage-audit-closeout-execution-design.md`
   - `docs/framework-defect-backlog.zh-CN.md`
   - `README.md`
   - `specs/052-framework-defect-gate-and-path-discipline/spec.md`
   - `specs/052-framework-defect-gate-and-path-discipline/plan.md`
   - `specs/052-framework-defect-gate-and-path-discipline/tasks.md`
   - `specs/052-framework-defect-gate-and-path-discipline/task-execution-log.md`
   - `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/execution-plan.yaml`
   - `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。

## 用户故事

### 用户故事 1：维护者需要在仓库内直接执行约束校验

作为维护者，我需要在当前仓库里直接运行 `python -m ai_sdlc verify constraints`，这样校验结果由仓库真值给出，而不是依赖外部站点包或别的工作区版本。

### 用户故事 2：formal 文档路径不能再漂移

作为维护者，我需要一个明确的 canonical path classifier，让总设计、单 WI formal 文档和 `docs/superpowers` 过程产物有稳定边界，这样后续回答和文档写入不会再次漂移。

### 用户故事 3：framework defect backlog 必须被机器校验

作为维护者，我需要 framework defect backlog 的存在性和字段完备性被自动检查，这样违约记录不会再被写错文件名、漏字段或绕过主 backlog。
