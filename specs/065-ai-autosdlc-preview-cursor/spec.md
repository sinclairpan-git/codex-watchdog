# Spec：065-ai-autosdlc-preview-cursor

## 背景

当前仓库已经在 `WI-062` / `WI-063` 完成 provider runtime、Memory Hub durable store 与异步 ingest，
但 `AI_AutoSDLC` 仍只有一个名为 `ai-autosdlc-cursor` 的 preview contract 名字，缺少可调用的 stage-aware
adapter 语义。这意味着框架设计中要求的 “AI_AutoSDLC 可以拿到 resident capsule / packet inputs / skills，
并在阶段上下文与当前 Goal Contract 冲突时 fail-closed” 还没有落地。

`WI-065` 的目标是把该 preview contract 从“仅占位名称”提升为真实可调用的 preview adapter，
同时继续保持 disabled-by-default，不把 Memory Hub advisory 提升为 Session Service truth source。

## 范围

### In Scope

- `src/watchdog/services/memory_hub/models.py`
- `src/watchdog/services/memory_hub/service.py`
- `src/watchdog/services/memory_hub/__init__.py`
- `tests/test_watchdog_memory_packets.py`
- `Memory Hub` / `Goal Contract` 相关 targeted 回归
- `ai_sdlc` work item 文档与状态同步

### Out of Scope

- 不把 `ai-autosdlc-cursor` 直接升级为默认启用的 production runtime；
- 不让 `stage` / `active_goal` 覆盖 `Goal Contract.current_phase_goal`；
- 不在本工单内实现新的 Brain orchestration surface；
- 不在本工单内替代 Session Service 的真值职责。

## Formal Source

- `docs/architecture/codex-watchdog-full-product-loop-design.md`
- `docs/architecture/codex-long-running-autonomy-design.md`
- `specs/060-memory-advisory-fail-closed-and-ops-hardening/spec.md`
- `specs/062-global-design-provider-memory-closure/spec.md`
- `src/watchdog/services/memory_hub/contracts.py`
- `src/watchdog/services/memory_hub/packets.py`

## 非 Owner 约束

- **FR-6501**：`AI_AutoSDLC` 只能消费 `Memory Hub` advisory context，不得自称 truth source。
- **FR-6502**：preview contract 必须默认关闭，只有显式 override 才能启用。
- **FR-6503**：`stage` / `active_goal` 只能作为 advisory context；如果与 `Goal Contract.current_phase_goal`
  冲突，返回必须降级到 `reference_only`。
- **FR-6504**：缺失 `current_phase_goal` 时也必须 fail-closed，不得升级为 advisory / authoritative。
- **FR-6505**：返回 payload 至少包含：
  - `resident_capsule`
  - `packet_inputs`
  - `skills`
  - `goal_alignment`
  - `precedence=session_service`

## 功能需求

- **FR-6506**：新增 `AIAutoSDLCCursorRequest`、`AIAutoSDLCCursorGoalAlignment` 与
  `AIAutoSDLCCursorResponse`，显式约束 preview adapter 的输入输出。
- **FR-6507**：`MemoryHubService` 必须支持 `preview_contract_overrides`，用于在测试或受控 runtime 中启用
  `ai-autosdlc-cursor`。
- **FR-6508**：`ai_autosdlc_cursor()` 必须在启用时返回基于项目上下文的 archive refs、resident capsule 与
  skills，并沿用 packet input contract。
- **FR-6509**：当 `active_goal != current_phase_goal` 时，`goal_alignment.status=conflict`，
  `goal_alignment.mode=reference_only`。
- **FR-6510**：当 `current_phase_goal` 缺失时，`goal_alignment.status=missing_goal_contract`，
  `goal_alignment.mode=reference_only`。
- **FR-6511**：当 `active_goal` 与 `current_phase_goal` 对齐时，返回 `goal_alignment.status=aligned`，
  `goal_alignment.mode=advisory`。
- **FR-6512**：targeted tests 必须证明：
  - enabled preview contract 会返回 stage-aware packet；
  - conflicting goal 会降级到 `reference_only`；
  - disabled-by-default 约束继续成立。

## Docs baseline hash recipe

`docs_baseline_ref` 生成方式沿用现有 work item 规则，artifact set 固定为：

- `specs/065-ai-autosdlc-preview-cursor/spec.md`
- `specs/065-ai-autosdlc-preview-cursor/plan.md`
- `specs/065-ai-autosdlc-preview-cursor/tasks.md`
- `specs/065-ai-autosdlc-preview-cursor/task-execution-log.md`
- `.ai-sdlc/work-items/065-ai-autosdlc-preview-cursor/execution-plan.yaml`
- `.ai-sdlc/work-items/065-ai-autosdlc-preview-cursor/latest-summary.md`
