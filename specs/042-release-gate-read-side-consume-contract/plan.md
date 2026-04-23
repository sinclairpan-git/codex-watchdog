---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/041-release-gate-artifact-refresh-and-rebuild-contract/spec.md"
  - "specs/042-release-gate-read-side-consume-contract/spec.md"
---

# 实施计划：042-release-gate-read-side-consume-contract

## 目标

把 `release_gate_verdict` 与 `release_gate_evidence_bundle` 的 read-side consume path 收口到单一 shared typed contract，确保 ops 与 resident runtime 读取 decision evidence 时不再复制字段路径和嵌套假设。

## 架构摘要

- **One typed read contract**：新增一个 shared helper / typed model，统一解析 release gate decision evidence。
- **Consumer reads, not reinterprets**：现有 read-side consumer 只读取 shared helper 的正式 surface，不再重新拼装 bundle/verdict 字段。
- **Fail closed on malformed evidence**：当 evidence 结构缺失或漂移时，consumer 只能降级消费，不能把残缺 evidence 当作完整 blocker metadata 或 formal pass evidence。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/042-release-gate-read-side-consume-contract/*` | 冻结 042 正式边界、任务拆解与 handoff |
| Shared read contract | `src/watchdog/services/brain/release_gate_read_contract.py` | 解析 decision evidence 中的 `release_gate_verdict` 与 `release_gate_evidence_bundle` |
| Read-side consumers | `src/watchdog/api/ops.py`, `src/watchdog/services/session_spine/orchestrator.py` | 只通过 shared helper 读取 blocker metadata 与 runtime qualification |
| Contract tests | `tests/test_watchdog_ops.py`, `tests/test_watchdog_session_spine_runtime.py` | 锁定 typed consume surface 与 malformed evidence fail-closed 纪律 |

## 边界纪律

- 042 不得新增新的 release gate policy、runtime gate taxonomy、report schema 或 evidence bundle schema。
- 042 不得新增新的 persistence model、query facade、ops projection 或 read platform。
- 042 可以收敛测试辅助，但测试改动只能服务 shared read contract 验证，不能把测试工厂整理变成主目标。
- 042 只处理 read-side consumer contract，不回到 refresh/platform/manifest 设计面。

## 依赖顺序

1. **先冻结 formal docs 与 042 work item 元数据**
   - 明确 042 只做 shared typed read-side consume contract；
   - 明确它不扩 schema、policy、persistence 或平台层。
2. **再写失败测试锁定 consume seam**
   - 先证明当前 consumer 还在手工剥取 evidence dict；
   - 先锁定 malformed / partial evidence 必须 fail closed。
3. **再补 shared helper 与 consumer 收口**
   - 新增 shared typed helper；
   - 修改 `ops.py` 与 resident runtime read-side consumer 使用该 helper。
4. **最后更新 handoff**
   - 固定后续任何新 consumer 都必须通过 shared read contract，而不是再复制 dict 路径。

## 分阶段计划

### Phase 1：冻结 042 formal docs、任务分解与执行元数据

交付内容：

- `specs/042-release-gate-read-side-consume-contract/spec.md`
- `specs/042-release-gate-read-side-consume-contract/plan.md`
- `specs/042-release-gate-read-side-consume-contract/tasks.md`
- `specs/042-release-gate-read-side-consume-contract/task-execution-log.md`
- `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/*`

### Phase 2：写失败测试锁定 read-side consume contract

交付内容：

- `tests/test_watchdog_ops.py`
- `tests/test_watchdog_session_spine_runtime.py`

### Phase 3：补齐 shared helper 与 consumer 收口

交付内容：

- `src/watchdog/services/brain/release_gate_read_contract.py`
- `src/watchdog/api/ops.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `tests/test_watchdog_ops.py`
- `tests/test_watchdog_session_spine_runtime.py`

### Phase 4：更新执行日志与 handoff 摘要

交付内容：

- `specs/042-release-gate-read-side-consume-contract/task-execution-log.md`
- `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/execution-plan.yaml`
- `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/runtime.yaml`
- `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/resume-pack.yaml`
- `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/latest-summary.md`

## 测试计划

- `tests/test_watchdog_ops.py`
  - 锁定 `ops.py` 必须通过 shared helper 读取 blocker metadata，并在 malformed / partial evidence 下 fail closed
- `tests/test_watchdog_session_spine_runtime.py`
  - 锁定 resident runtime 对 runtime pass qualification 的读取不再依赖裸 dict 假设
- `tests/test_long_running_autonomy_doc_contracts.py`
  - 锁定总实施计划与 canonical work item 元数据同步

## 主要风险与应对

### 风险 1：helper 只是换个地方继续复制 dict 假设

应对：

- helper 必须用正式 typed model / parsing 入口，不允许只是把 `dict.get(...)` 挪到新文件；
- 红测锁定 malformed / partial evidence 的 fail-closed 纪律。

### 风险 2：scope 滑向测试整理或新 read platform

应对：

- 把测试工厂整理、新 query facade、ops projection、manifest/platform 全部列为非目标；
- 只交付一个 shared helper 与 1-2 个现有 consumer 的收口。

## 验收口径

只有当以下条件同时满足，042 才算完成：

1. `release_gate_verdict + release_gate_evidence_bundle` 已有唯一 shared typed read contract；
2. `ops.py` 与 resident runtime 读侧已收敛到该 helper；
3. malformed / partial evidence 在 consumer 侧只能 fail closed；
4. 未引入新的 policy、schema、persistence、manifest 或 read platform。
