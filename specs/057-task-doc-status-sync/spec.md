# Spec：057-task-doc-status-sync

## 背景

`WI-056` 完成后，repo-local `python -m ai_sdlc verify constraints` 已通过，但 repo-wide residual scan 显示一类 formal memory 漂移仍然存在：

- 某些已完成 work item 的 `.ai-sdlc/work-items/<wi>/execution-plan.yaml` 与 `latest-summary.md` 明确标记为 completed；
- 对应 `specs/<wi>/tasks.md` 却仍残留 `进行中`、`待开始` 或 `未开始` 的任务状态文案。

当前已确认的典型样本包括：

- `specs/030-session-service-event-truth-write-barrier/tasks.md`
- `specs/048-missing-runtime-semantics-and-action-surface/tasks.md`
- `specs/049-feishu-entrypoint-closure/tasks.md`

这会造成同一 work item 在 formal truth 内出现两套状态：

1. `.ai-sdlc` 元数据与 `latest-summary.md` 认为已完成；
2. `tasks.md` 仍像是半途停在执行中。

`WI-057` 因此只承担 completed work item task-doc status drift 的 repo-side closeout：修正文档状态，并把该约束纳入 repo-local `verify constraints` 与回归测试。

## 范围

### In Scope

- completed WI 的 `specs/<wi>/tasks.md` 任务状态同步；
- task-doc status drift validator；
- 回归测试；
- 相关 formal docs、`.ai-sdlc` 状态与 closeout 留档。

### Out of Scope

- 不修改任何业务代码或运行时语义；
- 不重写 `execution-plan.yaml` 的历史任务边界；
- 不扩展到非 completed work item 的任务规划文案风格；
- 不修改外部 `Ai_AutoSDLC` 仓库。

## Formal Source

- `specs/030-session-service-event-truth-write-barrier/tasks.md`
- `specs/048-missing-runtime-semantics-and-action-surface/tasks.md`
- `specs/049-feishu-entrypoint-closure/tasks.md`
- `.ai-sdlc/work-items/030-session-service-event-truth-write-barrier/execution-plan.yaml`
- `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/execution-plan.yaml`
- `.ai-sdlc/work-items/049-feishu-entrypoint-closure/execution-plan.yaml`
- `.ai-sdlc/work-items/030-session-service-event-truth-write-barrier/latest-summary.md`
- `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/latest-summary.md`
- `.ai-sdlc/work-items/049-feishu-entrypoint-closure/latest-summary.md`

## 非 Owner 约束

- **FR-5701**：057 只关闭 completed WI 的 task-doc status drift，不修改业务语义。
- **FR-5702**：057 不得改写 `execution-plan.yaml` 的任务定义或历史时间戳，只能让 `tasks.md` 跟已冻结的执行结果一致。
- **FR-5703**：057 不得把 `tasks.md` 提升为独立真值源；它仍然是 formal mirror，但必须与 `.ai-sdlc` 生命周期同步。

## 功能需求

- **FR-5704**：若某个 work item 的 `latest-summary.md` 为 `Status: completed`，且 `execution-plan.yaml` 中全部 task 已为 `completed`，则对应 `specs/<wi>/tasks.md` 不得继续包含 `进行中`、`待开始` 或 `未开始`。
- **FR-5705**：repo-local `python -m ai_sdlc verify constraints` 必须覆盖上述 completed task-doc status contract。
- **FR-5706**：057 至少要修正当前已确认漂移的 `WI-030`、`WI-048`、`WI-049`。
- **FR-5707**：057 必须用回归测试覆盖：
  1. 当前仓库满足 completed task-doc status contract；
  2. 临时 completed WI 的 `tasks.md` 若残留 `进行中/待开始/未开始`，validator 明确失败；
  3. 临时 repo 缺少对应 `execution-plan.yaml` 或 `latest-summary.md` 时，validator 只按存在的 completed evidence 判断，不误报不存在的 WI。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。057 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/architecture/coverage-audit-closeout-execution-design.md`
   - `specs/030-session-service-event-truth-write-barrier/tasks.md`
   - `specs/048-missing-runtime-semantics-and-action-surface/tasks.md`
   - `specs/049-feishu-entrypoint-closure/tasks.md`
   - `specs/057-task-doc-status-sync/spec.md`
   - `specs/057-task-doc-status-sync/plan.md`
   - `specs/057-task-doc-status-sync/tasks.md`
   - `specs/057-task-doc-status-sync/task-execution-log.md`
   - `.ai-sdlc/work-items/057-task-doc-status-sync/execution-plan.yaml`
   - `.ai-sdlc/work-items/057-task-doc-status-sync/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
