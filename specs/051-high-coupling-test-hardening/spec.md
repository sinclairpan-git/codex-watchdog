# Spec：051-high-coupling-test-hardening

## 背景

`WI-050` 已正式关闭 observability / restart / security / acceptance 的 release-blocking 条款，并在 handoff 中明确：后续只允许进入 `WI-051` 的高耦合 hardening，不再承接 release blocker。

与此同时，项目 backlog 中的 `BL-2026-04-06-001` 已明确指出，`Codex bridge -> approval callback -> restart restore -> session spine` 这条接缝当前的问题不再是“完全没测”，而是测试仍偏点状补丁式回归，缺少显式场景矩阵、测试替身契约，以及固定的验证入口。

`WI-051` 因此只接手以下正式职责：

1. 把 backlog 中 deferred 的高耦合测试强化转成 formal spec / plan / tasks；
2. 把 approval / callback / restart / session spine 的关键高风险 seam 收敛成显式矩阵；
3. 补齐 fake / stub 与真实 `AClient` 接口漂移的契约护栏；
4. 固定 `targeted / seam-smoke / full` 三层验证入口，但不改上游产品语义。

## 范围

### In Scope

- `BL-2026-04-06-001` 中明确列出的高耦合测试强化；
- `approval / callback / restart / session spine` 的最小高价值场景矩阵；
- fake / stub / real client 接口签名与过滤语义契约测试；
- `targeted / seam-smoke / full` 三层验证入口的固定；
- 对现有高风险测试进行矩阵归档、去重复和正式回归编排。

### Out of Scope

- 任何 release blocker 条款；
- 任何 runtime semantics、canonical action、policy truth 的改写；
- 任何 Feishu / Feishu 正式入口定义或入口行为扩展；
- 任何前端 / UI 自动化；
- 为了测试强化而新增上游业务真源或重新定义 state contract。

## Formal Source

- `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `### 4.5 WI-051：High-Coupling Test Hardening`
  - `### 4.6 Owner Ledger 与依赖图`
- `docs/project-backlog.zh-CN.md`
  - `## BL-2026-04-06-001 前端强化后执行测试模块强化`
- `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/latest-summary.md`
  - `WI-050 已完成 formal closeout；剩余工作只允许进入 WI-051 的高耦合 hardening`
- `specs/050-observability-restart-security-and-acceptance/spec.md`
  - `为 WI-051 留下的只应是高耦合 hardening，而不是 release blocker`

## 非 Owner 约束

- **FR-5101**：051 只能消费 `WI-049` / `WI-050` 已冻结的正式 surface，不得新增或改写产品行为。
- **FR-5102**：051 不得承接任何 coverage matrix owner 行，也不得伪装成“继续清 release blocker”。
- **FR-5103**：051 的所有新增工作必须可归类为测试矩阵、测试替身契约或验证入口固定。

## 功能需求

- **FR-5104**：必须将 backlog 中 `approval / callback / restart / session spine` 接缝整理为正式场景矩阵，并与测试 1:1 映射。
- **FR-5105**：必须补齐 fake / stub 与真实 `AClient` 之间的接口签名与关键过滤语义契约测试；当真实接口扩展或变更时，测试替身必须直接失败，而不是静默漂移。
- **FR-5106**：必须固定三层验证入口：
  1. `targeted`：最小高价值局部回归；
  2. `seam-smoke`：覆盖整条 `approval -> callback -> restart -> stable read semantics` 接缝；
  3. `full`：纳入正式全量回归说明。
- **FR-5107**：必须明确哪些已有测试被视为正式矩阵项，哪些属于重复覆盖而不再扩写。
- **FR-5108**：051 若发现真实缺口，可记录为后续实现入口，但本 work item 本身不得默认扩大为生产代码增强项。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。051 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/architecture/coverage-audit-closeout-execution-design.md`
   - `docs/project-backlog.zh-CN.md`
   - `specs/051-high-coupling-test-hardening/spec.md`
   - `specs/051-high-coupling-test-hardening/plan.md`
   - `specs/051-high-coupling-test-hardening/tasks.md`
   - `specs/051-high-coupling-test-hardening/seam-matrix.md`
   - `specs/051-high-coupling-test-hardening/task-execution-log.md`
   - `.ai-sdlc/work-items/051-high-coupling-test-hardening/execution-plan.yaml`
   - `.ai-sdlc/work-items/051-high-coupling-test-hardening/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。

## 用户故事

### 用户故事 1：维护者需要知道哪些 seam 已被正式覆盖

作为维护者，我需要一份显式的高耦合场景矩阵，把 callback、restart、session spine 等关键接缝与现有测试一一对应，而不是依赖历史 review 记忆判断“这块应该测过了”。

### 用户故事 2：测试替身不能静默漂移

作为维护者，我需要 fake / stub 在真实 `AClient` 接口变更时直接失败，这样测试不会因为替身签名滞后而产生虚假的通过。

### 用户故事 3：验证入口必须固定

作为执行者，我需要明确的 `targeted / seam-smoke / full` 三层入口，这样后续强化和回归有统一运行方式，而不是临时拼命令。
