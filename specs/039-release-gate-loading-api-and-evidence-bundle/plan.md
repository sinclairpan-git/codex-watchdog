---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"
  - "specs/038-future-worker-canonical-execution-and-governance/spec.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
---

# 实施计划：039-release-gate-loading-api-and-evidence-bundle

## 目标

把 `release_gate_report` 的加载/校验 contract 与 `release_gate_evidence_bundle` 的回读 surface 收口成共享 API，避免后续入口重复解析规则。

## 架构摘要

- **One loader, one answer**：`release_gate_report` 的 parse/validate/hash/drift 判定只允许通过单一 shared loader 完成。
- **Bundle, not fragments**：formal artifacts 与 blocker metadata 通过统一 evidence bundle 暴露，而不是由 orchestrator / ops / future consumers 各自拼接。
- **Fail closed stays canonical**：039 只收口 shared contract，不新增新的放行语义或 read-side 第二真相。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/039-release-gate-loading-api-and-evidence-bundle/*` | 冻结 039 正式边界、任务拆解与 handoff |
| Shared loading contract | `src/watchdog/services/brain/release_gate.py`, `src/watchdog/services/brain/release_gate_loading.py` | 统一 `release_gate_report` 的读取、校验、hash exactness、runtime contract drift 判定 |
| Evidence bundle surface | `src/watchdog/services/brain/release_gate_evidence.py` | 暴露 `certification_packet_corpus`、`shadow_decision_ledger`、`label_manifest`、artifact refs 与治理元数据 |
| Runtime / read-side consumers | `src/watchdog/services/session_spine/orchestrator.py`, `src/watchdog/api/ops.py`, `src/watchdog/observability/metrics_export.py` | 改为只消费 shared loader / bundle 输出 |
| Contract tests | `tests/test_watchdog_release_gate.py`, `tests/test_watchdog_release_gate_evidence.py`, `tests/test_watchdog_ops.py`, `tests/test_watchdog_session_spine_runtime.py` | 锁定 shared loading / bundle / read-side 统一 contract |

## 边界纪律

- 039 不得新增新的 release gate blocker taxonomy、policy gate 或放行门槛。
- 039 不得让 ops/read-side 自行重算 report validity。
- 039 不得为 future worker、Feishu 或其他入口复制一份“局部兼容解析器”。
- 039 只消费 035/037/038 已冻结 contract，不回退到手写 report 直通 runtime。

## 依赖顺序

1. **先冻结 formal docs 与 039 work item 元数据**
   - 明确 039 只做 shared loading API / evidence bundle；
   - 明确它不扩新的 release gate 行为。
2. **再写失败测试锁定 shared loading / bundle contract**
   - 先证明当前实现仍主要停留在局部 helper 与 read-side 拼接；
   - 先锁定后续入口不得复制解析逻辑。
3. **再补 shared loader 与 evidence bundle**
   - 在 brain/release_gate 与 release_gate_evidence 中收口共享 surface；
   - 让 orchestrator / ops / metrics 改为只消费 canonical 输出。
4. **最后更新 handoff**
   - 固定后续任何消费 release gate 的入口都必须复用 shared contract。

## 分阶段计划

### Phase 1：冻结 039 formal docs、任务分解与执行元数据

交付内容：

- `specs/039-release-gate-loading-api-and-evidence-bundle/spec.md`
- `specs/039-release-gate-loading-api-and-evidence-bundle/plan.md`
- `specs/039-release-gate-loading-api-and-evidence-bundle/tasks.md`
- `specs/039-release-gate-loading-api-and-evidence-bundle/task-execution-log.md`
- `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/*`

### Phase 2：写失败测试锁定 shared loading API 与 evidence bundle

交付内容：

- `tests/test_watchdog_release_gate.py`
- `tests/test_watchdog_release_gate_evidence.py`
- `tests/test_watchdog_ops.py`
- `tests/test_watchdog_session_spine_runtime.py`

### Phase 3：补齐 shared loading API 与 evidence bundle

交付内容：

- `src/watchdog/services/brain/release_gate_loading.py`
- `src/watchdog/services/brain/release_gate.py`
- `src/watchdog/services/brain/release_gate_evidence.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/api/ops.py`
- `src/watchdog/observability/metrics_export.py`

### Phase 4：更新执行日志与 handoff 摘要

交付内容：

- `specs/039-release-gate-loading-api-and-evidence-bundle/task-execution-log.md`
- `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/execution-plan.yaml`
- `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/runtime.yaml`
- `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/resume-pack.yaml`
- `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/latest-summary.md`

## 测试计划

- `tests/test_watchdog_release_gate.py`
  - 锁定 shared loader 的 JSON object guard、canonical hash exactness、runtime contract drift 与 fail-closed 语义
- `tests/test_watchdog_release_gate_evidence.py`
  - 锁定 formal artifacts 与 evidence bundle 的统一读取面
- `tests/test_watchdog_ops.py`
  - 锁定 ops/read-side 只消费 shared loader / bundle 输出
- `tests/test_watchdog_session_spine_runtime.py`
  - 锁定 orchestrator/runtime 只消费 shared loader 的 canonical verdict

## 主要风险与应对

### 风险 1：新入口继续复制 report 解析逻辑

应对：

- 用 shared loading API 明确唯一入口；
- 用测试锁定后续入口不得自己 parse/validate。

### 风险 2：ops/read-side 和 runtime 再次出现 blocker 第二真相

应对：

- 用 evidence bundle 收口 formal artifacts 与 blocker metadata；
- 禁止 read-side 自行重算 report validity。

## 验收口径

只有当以下条件同时满足，039 才算完成：

1. `release_gate_report` 的加载/校验 contract 已有唯一 shared API；
2. `release_gate_evidence_bundle` 已形成统一回读 surface；
3. runtime、ops/read-side 与后续入口都只消费 shared loader / bundle；
4. `report_load_failed` 等 fail-closed 语义未被稀释或分叉。
