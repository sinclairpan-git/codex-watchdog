---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/034-memory-hub-codex-critical/spec.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/036-feishu-control-plane-primary-surface/spec.md"
  - "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"
  - "specs/038-future-worker-canonical-execution-and-governance/spec.md"
---

# 实施计划：038-future-worker-canonical-execution-and-governance

## 目标

把 future worker / sub-agent 从声明式预留 schema，升级成受 canonical truth、recovery、ops 与 Feishu governance 共同约束的正式 execution contract。

## 架构摘要

- **Worker is not truth**：worker/sub-agent 只产生受限 result envelope 与 summary refs；真正生效必须经过 parent canonical consume。
- **Freeze refs, then execute**：worker 只能消费 parent 在 spawn 时冻结的 `DecisionTrace`、packet refs、retrieval handles 与 distilled summary，不能在运行期偷读 live truth。
- **Lifecycle must be canonical**：worker requested / started / heartbeat / summary / completed / failed / cancelled / consumed / rejected 都必须进入 `Session Service`，不能只留在进程内状态。
- **Reuse existing contracts**：038 只消费 033-037 已冻结的 recovery、memory refs、brain trace、Feishu interaction 与 completion evidence contract，不新造第二状态机。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/038-future-worker-canonical-execution-and-governance/*` | 冻结 038 的正式边界、任务拆解与 handoff |
| Worker contract models | `src/watchdog/services/future_worker/models.py`, `src/watchdog/services/brain/models.py`, `src/watchdog/services/memory_hub/models.py` | 定义 worker execution contract、result envelope、budget/scope、frozen refs 与与既有 trace/ref contract 的对接 |
| Canonical truth writer | `src/watchdog/services/session_service/models.py`, `src/watchdog/services/session_service/service.py` | 增加 future worker lifecycle events、result consume/reject 记录、supersede/cancel 治理 |
| Runtime integration | `src/watchdog/services/future_worker/service.py`, `src/watchdog/services/session_spine/orchestrator.py`, `src/watchdog/services/session_spine/recovery.py` | 负责 worker 请求、spawn/consume、stale result 拒绝与 recovery continuation |
| Read-side / ops surfacing | `src/watchdog/api/ops.py`, `src/watchdog/observability/metrics_export.py` | 暴露 worker 状态层级、阻断原因、supersede 与 late-result rejection |
| Contract / e2e tests | `tests/test_watchdog_future_worker_contract.py`, `tests/test_watchdog_future_worker_runtime.py`, `tests/e2e/test_watchdog_future_worker_execution.py` | 冻结 038 的正式 contract、runtime 与 e2e 主链 |

## 边界纪律

- 038 不得为 worker/sub-agent 定义独立真相层或进程内“已生效”状态。
- 038 不得让 worker 直接写 Goal Contract、approval、completion truth、release gate verdict 或 command lease。
- 038 不得让 worker 绕过 034 的 retrieval/ref contract 去读取 Memory Hub 私有热路径。
- 038 不得把 worker orchestration 扩张成通用队列平台或外部执行器抽象。
- 038 不得为人工确认另起一套协议；涉及人工干预的 worker 操作继续走 036 的 Feishu interaction contract。

## 依赖顺序

1. **先冻结 formal docs 与 038 work item 元数据**
   - 明确 038 是 035 预留 future worker contract 的正式实现项；
   - 明确 038 的关注点是 canonical execution contract，而不是“多 worker 能跑”。
2. **再写失败测试锁定 worker canonical lifecycle**
   - 先证明当前仓库只有声明式 `FutureWorkerTraceRef`，没有正式 lifecycle / consume / reject contract；
   - 先锁定 stale/late/duplicate/supersede 都必须 fail closed。
3. **再补 Session truth 与 runtime glue**
   - 在 Session Service、future_worker service、orchestrator、recovery 中把 worker requested/start/complete/consume/reject 串通；
   - 保证 worker 仍只消费 frozen refs。
4. **再收口 ops/read-side 与 e2e**
   - 让 ops 和 e2e 都能看见 worker 运行层级与阻断原因；
   - 让正式主链覆盖 parent consume worker result 的闭环。
5. **最后更新 handoff**
   - 固定 038 完成后，后续多 worker / sub-agent 工作只能继续消费这套 canonical contract。

## 分阶段计划

### Phase 1：冻结 038 formal docs、任务分解与执行元数据

交付内容：

- `specs/038-future-worker-canonical-execution-and-governance/spec.md`
- `specs/038-future-worker-canonical-execution-and-governance/plan.md`
- `specs/038-future-worker-canonical-execution-and-governance/tasks.md`
- `specs/038-future-worker-canonical-execution-and-governance/task-execution-log.md`
- `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/*`

关键原则：

- 先收紧 038 的核心目标：canonical worker execution contract，而不是泛化 worker framework；
- 明确它只消费 033-037 已冻结边界。

### Phase 2：写失败测试锁定 worker lifecycle、consume/reject 与 stale-result fail-closed

交付内容：

- `tests/test_watchdog_future_worker_contract.py`
- `tests/test_watchdog_future_worker_runtime.py`
- `tests/e2e/test_watchdog_future_worker_execution.py`

关键原则：

- 红测优先锁定 worker 生命周期进入 Session truth；
- 红测优先锁定 parent consume 与 stale/late/duplicate/supersede rejection。

### Phase 3：补齐 canonical worker execution truth 与 runtime glue

交付内容：

- `src/watchdog/services/future_worker/models.py`
- `src/watchdog/services/future_worker/service.py`
- `src/watchdog/services/session_service/models.py`
- `src/watchdog/services/session_service/service.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/services/session_spine/recovery.py`

关键原则：

- worker lifecycle、result envelope 与 consume/reject 都进入 canonical truth；
- 不新增第二状态机，不让 worker 结果直接等于真相。

### Phase 4：收口 ops surfacing 与 formal worker e2e

交付内容：

- `tests/test_watchdog_future_worker_runtime.py`
- `tests/e2e/test_watchdog_future_worker_execution.py`
- `src/watchdog/api/ops.py`
- `src/watchdog/observability/metrics_export.py`

关键原则：

- ops/read-side 必须能看到 worker 在哪一层被阻断；
- e2e 必须覆盖至少一条 worker 正式主链和一条 stale/late rejection 支线。

### Phase 5：更新执行日志与 handoff 摘要

交付内容：

- `specs/038-future-worker-canonical-execution-and-governance/task-execution-log.md`
- `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/execution-plan.yaml`
- `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/runtime.yaml`
- `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/resume-pack.yaml`
- `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md`

关键原则：

- handoff 必须明确 worker 结果何时才算真正生效；
- 后续 worker/sub-agent 工作不得回退到隐式共享状态或人工口头治理。

## 测试计划

- `tests/test_watchdog_future_worker_contract.py`
  - 冻结 worker execution contract、scope/budget、frozen refs 与越权字段禁止清单
- `tests/test_watchdog_future_worker_runtime.py`
  - 覆盖 worker requested/start/heartbeat/summary/completed/failed/cancelled/consumed/rejected
  - 覆盖 stale completion、duplicate start、superseded result 与 scope drift fail-closed
- `tests/e2e/test_watchdog_future_worker_execution.py`
  - 固定 `parent decision -> worker requested -> worker started -> summary published -> worker completed -> parent consumes result -> follow-up decision/completion evidence updated`
  - 固定 crash recovery / late result rejection / supersede 不能污染主链

## 主要风险与应对

### 风险 1：worker 结果被误当成已生效真相

应对：

- 强制区分 worker completed 与 worker result consumed；
- consume 前不允许 worker 结果直接推进 completion / approval / goal state。

### 风险 2：worker 越权读取 live truth 或 Memory Hub 私有状态

应对：

- worker 只消费 frozen refs；
- retrieval/ref contract 继续复用 034，禁止再造 worker-only context 通道。

### 风险 3：worker crash / late result 形成第二条隐式状态机

应对：

- 复用 033 recovery transaction 与 supersede 语义；
- stale/late/duplicate 统一进入 canonical reject/audit 路径。

## 验收口径

只有当以下条件同时满足，038 才算完成：

1. future worker / sub-agent 已拥有正式 canonical execution contract，而不只是声明式预留 schema；
2. worker lifecycle 与 result consume/reject 全部进入 Session truth；
3. worker 只消费 frozen refs，不能越权取数或直接改 parent truth；
4. stale/late/duplicate/supersede/crash recovery 都有 fail-closed canonical 语义；
5. ops/read-side 与 e2e 都能看见 worker 运行层级与阻断原因。
