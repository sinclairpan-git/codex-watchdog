# Spec：050-observability-restart-security-and-acceptance

## 背景

`WI-048` 已冻结 runtime semantics / canonical action surface，`WI-049` 已补齐 Feishu primary entry、OpenClaw compatibility entry 与自然语言到 canonical route 的正式入口闭环。当前剩余 release-blocking 条款，不再是“入口有没有”，而是这些入口与 runtime contract 在非功能要求、重启恢复、安全边界、可观测性与最终验收上的闭环证据。

`WI-050` 因此接手以下剩余正式职责：

1. 把 PRD 第 14 章的性能、可用性、可观测性要求收敛为可验证 contract；
2. 把 PRD 第 13 章安全要求与第 17 章验收标准转成稳定测试和 evidence；
3. 确保 A-Control-Agent / Watchdog 在重启后仍维持 project/thread、审批和最近动作的恢复闭环；
4. 为 `WI-051` 留下的只应是高耦合 hardening，而不是 release blocker。

## 范围

### In Scope

- `P95 < 3s` 的查询/读取路径验证与 evidence 固化；
- `/healthz`、结构化日志、基础指标导出与任务/审批/恢复相关统计；
- A-Control-Agent 重启后的 `project_id <-> thread_id` 连续性验证；
- Watchdog 重启后的待审批、最近动作与 receipt 状态恢复验证；
- A 不可达时，B 必须 fail-closed 返回控制链路异常；
- PRD 17.1 / 17.2 / 17.3 中仍未被 048/049 关闭的验收条款。

### Out of Scope

- 不重开 `WI-048` 的 runtime semantics、policy truth、Memory Hub precedence；
- 不重开 `WI-049` 的入口语义、intent catalog、Feishu/OpenClaw route contract；
- 不进入 `WI-051` 的专项高耦合 hardening、广谱回归扩写或非 blocker 美化。

## Formal Source

- `openclaw-codex-watchdog-prd.md`
  - `## 13. 安全要求`
  - `### 14.1 性能`
  - `### 14.2 可用性`
  - `### 14.3 可观测性`
  - `## 17. 验收标准`
  - `### M5：加固与验收`
- `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `### Task 8: 固化一期通关验收与端到端 release gate`
- `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml`
  - `matrix-row-0061`
- `specs/049-feishu-and-openclaw-entrypoint-closure/*`

## 功能需求

- **FR-5001**：必须为 Watchdog 主查询路径提供可重放的性能 evidence，覆盖“进展查询 / 状态读取 / 阻塞解释”等正式入口，至少能判断是否满足 PRD 的 `P95 < 3s` 目标。
- **FR-5002**：必须提供 `/healthz` 与基础 observability evidence，至少覆盖结构化日志、任务/审批/恢复相关指标，以及失败时可审计的控制链路错误。
- **FR-5003**：必须验证 A-Control-Agent 重启后 `project_id <-> native_thread_id` 映射仍可恢复，且 Feishu/OpenClaw 正式入口继续可查询。
- **FR-5004**：必须验证 Watchdog 重启后 pending approvals、最近动作 receipts 与关键 runtime 状态不丢失。
- **FR-5005**：当 A 不可达或上游 envelope 非法时，B 侧必须返回显式 `CONTROL_LINK_ERROR` 或等价 fail-closed reply，禁止伪装成“任务仍正常运行”。
- **FR-5006**：必须把 PRD `17.1/17.2/17.3` 中仍未关闭的验收条款转成稳定测试或可执行 evidence bundle，而不是停留在 README/summary 说明。
- **FR-5007**：050 只能消费 048/049 已冻结 contract，任何性能/可用性/验收实现不得改写 canonical semantics。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。050 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
   - `specs/050-observability-restart-security-and-acceptance/spec.md`
   - `specs/050-observability-restart-security-and-acceptance/plan.md`
   - `specs/050-observability-restart-security-and-acceptance/tasks.md`
   - `specs/050-observability-restart-security-and-acceptance/task-execution-log.md`
   - `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/execution-plan.yaml`
   - `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。

## 用户故事

### 用户故事 1：运维需要知道入口链路是否真的可用

作为运维或值班人，我需要通过 `/healthz`、结构化日志和指标快速判断 Watchdog 是否可用、控制链路是否异常、审批与恢复动作是否正在堆积，而不是只能靠人工翻日志猜测。

### 用户故事 2：系统重启后任务不能“失忆”

作为操作者，我需要在 A-Control-Agent 或 Watchdog 重启后，仍能继续按 `project_id` 或 `native_thread_id` 查询任务，并看到待审批和最近动作状态，而不是因为进程重启就丢掉上下文。

### 用户故事 3：发布前需要有正式验收证据

作为维护者，我需要一组稳定的 acceptance evidence，证明性能、可用性、安全和 observability 条款都被验证过，这样 release gate 才有客观依据，而不是依赖口头确认。
