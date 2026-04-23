# Spec：062-global-design-provider-memory-closure

## 背景

对照 `docs/architecture/codex-long-running-autonomy-design.md` 与
`docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md` 重新核对后，
当前工程距离原始全局设计仍有一组未完成、但彼此强耦合的闭环缺口：

1. `Brain` 仍以 rule-based intent 为主，尚未接入可运行的 `OpenAI-compatible` inference provider；
2. `Memory Hub` 仅具备 contract / packet / in-process archive search，缺少独立长期记忆所要求的持久化、摄取与 resident capsule；
3. `Session Service -> Memory Hub -> Brain/Recovery` 的主路径还没有形成“先写真相、再异步沉淀、再稳定检索”的持续闭环；
4. 当前文档里对 Task 5 / Task 6 的部分完成描述已超前于代码真值，需要通过新的 formal owner 收敛回真实状态。

`WI-062` 的目标不是新增一条旁路能力，而是把“外部模型辅助决策 + 长期记忆沉淀”两条主链补到符合原始全局设计的最小可运行状态。

## 范围

### In Scope

- `src/watchdog/services/brain/`
- `src/watchdog/services/memory_hub/`
- `src/watchdog/services/session_service/`
- `src/watchdog/services/session_spine/`
- `src/watchdog/main.py`
- `src/watchdog/settings.py`
- `tests/test_watchdog_memory_hub.py`
- `tests/test_watchdog_memory_packets.py`
- `tests/test_watchdog_memory_degradation.py`
- `tests/test_watchdog_provider_certification.py`
- `tests/test_watchdog_brain_decision_loop.py`

### Out of Scope

- 不重做已经通过验证的 Feishu 主控制面语义；
- 不新增高风险自动执行权限；
- 不把 `AI_AutoSDLC` preview contract 提升为一期 release blocker；
- 不实现通用多租户 memory platform。

## Formal Source

- `docs/architecture/codex-long-running-autonomy-design.md`
- `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
- `src/watchdog/services/brain/service.py`
- `src/watchdog/services/brain/provider_certification.py`
- `src/watchdog/services/memory_hub/service.py`
- `src/watchdog/services/memory_hub/indexer.py`
- `src/watchdog/services/session_service/service.py`
- `src/watchdog/main.py`

## 非 Owner 约束

- **FR-6201**：`Session Service + Goal Contract` 仍是运行时真源，`Memory Hub` 只能提供 advisory retrieval 与 packet inputs。
- **FR-6202**：外部模型只能通过 `OpenAI-compatible` contract 接入，且失败时必须 fail-closed 回退到现有 rule-based 决策。
- **FR-6203**：`Memory Hub` 的持久化沉淀必须在 Session 真相写入成功之后发生，不得反向阻塞或覆盖真相事件。
- **FR-6204**：`AI_AutoSDLC`、`User Model`、`Periodic Nudge` 仍保持 preview / disabled-by-default。

## 功能需求

- **FR-6205**：`Brain` 必须支持配置化的 `OpenAI-compatible` provider（`base_url + token + model`）。
- **FR-6206**：`Brain` 必须把 provider 的结构化输出映射为现有 canonical intent，并在 provider 不可用时稳定回退。
- **FR-6207**：`DecisionTrace` / runtime contract 必须能反映真实 provider/model，而不是始终写死为 `rule-based-brain`。
- **FR-6208**：`Memory Hub` 必须具备独立持久化层，可跨进程/重启保留 project registration、resident memory、archive entries 与 skill metadata。
- **FR-6209**：`Memory Hub` 必须支持最小 ingestion：project register、session event archive ingest、resident memory upsert、archive retrieval。
- **FR-6210**：`Memory Hub.build_runtime_advisory_context()` 必须返回 resident capsule，并继续保持 archive refs / skills / degradation 语义。
- **FR-6211**：应用启动后必须把 `Session Service` 事件写入异步沉淀到 `Memory Hub`，至少覆盖 `goal_contract_*`、`decision_*`、`command_*`、`recovery_*` 等长期可追溯事件。
- **FR-6212**：`WI-062` 必须以 targeted tests 证明 provider runtime 与 durable memory 都真实存在，而不是仅有文档或占位 contract。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式沿用现有 work item 规则：

1. reviewed formal artifact set 固定为：
   - `specs/062-global-design-provider-memory-closure/spec.md`
   - `specs/062-global-design-provider-memory-closure/plan.md`
   - `specs/062-global-design-provider-memory-closure/tasks.md`
   - `specs/062-global-design-provider-memory-closure/task-execution-log.md`
   - `.ai-sdlc/work-items/062-global-design-provider-memory-closure/execution-plan.yaml`
   - `.ai-sdlc/work-items/062-global-design-provider-memory-closure/latest-summary.md`
2. 统一换行归一化为 `LF`；
3. 缺失末尾换行时补一个 `LF`；
4. 按固定顺序拼接 `<<<PATH:{repo-root-relative-path}>>>` 与正文；
5. 对 UTF-8 payload 计算 `SHA-256`，输出小写十六进制字符串写入 `docs_baseline_ref`。
