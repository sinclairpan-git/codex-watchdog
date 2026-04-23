---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/045-resident-runtime-release-gate-evidence-write-contract/spec.md"
---

# 实施计划：045-resident-runtime-release-gate-evidence-write-contract

## 目标

把 resident runtime 中的 release-gate evidence 写侧组装收口到 shared write-side contract，确保 `_decision_evidence_for_intent()` 不再直接手工拼装 `release_gate_verdict` / `release_gate_evidence_bundle`。

## 架构摘要

- **One release-gate write seam**：resident runtime 通过 shared write-side helper 统一组装正式 report path 与 fallback path 的 release-gate evidence。
- **Reuse existing typed models**：优先复用 `ReleaseGateVerdict`、`ReleaseGateEvidenceBundle` 与 `LoadedReleaseGateArtifacts`，只补 shared write helper，不再新建第二套 evidence model。
- **Evidence shape stays fixed**：本 work item 只收敛写侧组装 seam，保持现有 decision evidence surface、read-side consume 与 policy semantics 不变。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/045-resident-runtime-release-gate-evidence-write-contract/*` | 冻结 045 正式边界、任务拆解与 handoff |
| Shared write helper | `src/watchdog/services/brain/release_gate_write_contract.py` | 统一组装 runtime decision evidence 中的 `release_gate_verdict` / `release_gate_evidence_bundle`，不接管其他 evidence 字段 |
| Resident runtime | `src/watchdog/services/session_spine/orchestrator.py` | 只通过 shared write-side helper 产出 release-gate evidence |
| Contract tests | `tests/test_watchdog_session_spine_runtime.py` | 锁定正式 report path / fallback path 都走统一 write-side contract |

## 边界纪律

- 045 不得新增新的 policy 规则、schema、persistence、manifest、archive metadata 或 query facade。
- 045 不得把参数命名整理、fixture helper 整理或 e2e 改造拔高成主目标。
- 045 只收敛 resident runtime 的 release-gate evidence 写侧组装，不回到 read-side、policy 或 workflow 设计面。

## 依赖顺序

1. **先冻结 formal docs 与 045 work item 元数据**
   - 明确 045 只做 release-gate evidence write-side contract；
   - 明确它不扩 schema、policy 或平台层。
2. **再写失败测试锁定 write seam**
   - 先证明当前 resident runtime 仍直接在 orchestrator 内联组装 verdict/bundle；
   - 先锁定正式 report path 与 fallback path 都必须通过同一 helper。
3. **再补 shared helper 与 orchestrator 收口**
   - 优先复用现有 release-gate typed models；
   - 让 `_decision_evidence_for_intent()` 只调用 shared helper。
4. **最后更新 handoff**
   - 固定后续任何 resident runtime producer 都必须复用同一 write-side contract。

## 分阶段计划

### Phase 1：冻结 045 formal docs、任务分解与执行元数据

交付内容：

- `specs/045-resident-runtime-release-gate-evidence-write-contract/spec.md`
- `specs/045-resident-runtime-release-gate-evidence-write-contract/plan.md`
- `specs/045-resident-runtime-release-gate-evidence-write-contract/tasks.md`
- `specs/045-resident-runtime-release-gate-evidence-write-contract/task-execution-log.md`
- `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/*`

### Phase 2：写失败测试锁定 release-gate evidence write-side contract

交付内容：

- `tests/test_watchdog_session_spine_runtime.py`

### Phase 3：补齐 shared write helper 与 resident runtime 收口

交付内容：

- `src/watchdog/services/brain/release_gate_write_contract.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `tests/test_watchdog_session_spine_runtime.py`

### Phase 4：更新执行日志与 handoff 摘要

交付内容：

- `specs/045-resident-runtime-release-gate-evidence-write-contract/task-execution-log.md`
- `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/execution-plan.yaml`
- `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/runtime.yaml`
- `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/resume-pack.yaml`
- `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/latest-summary.md`

## 测试计划

- `tests/test_watchdog_session_spine_runtime.py`
  - 锁定 resident runtime 通过 shared write-side contract 组装正式 report path / fallback path 的 release-gate evidence
- `tests/test_long_running_autonomy_doc_contracts.py`
  - 锁定总实施计划与 canonical work item 元数据同步

## 主要风险与应对

### 风险 1：把写侧收口变成 evidence schema 改写

应对：

- 红测只锁 existing evidence shape 与 shared helper surface；
- 保持现有 `release_gate_verdict` / `release_gate_evidence_bundle` 结构不变。

### 风险 2：scope 滑向 parameter rename 或 e2e 整理

应对：

- 把参数命名调整、fixture helper、e2e 改造明确列为非目标；
- 只交付 resident runtime write seam 收口与必要 contract tests。

## 验收口径

只有当以下条件同时满足，045 才算完成：

1. resident runtime 已通过 shared write-side contract 组装 `release_gate_verdict` / `release_gate_evidence_bundle`；
2. 正式 report path 与 report load failure fallback 都走统一 helper；
3. 现有 evidence shape、read-side 与 policy consumer 无需额外适配；
4. 未引入新的 policy、schema、manifest、persistence 或测试平台。
