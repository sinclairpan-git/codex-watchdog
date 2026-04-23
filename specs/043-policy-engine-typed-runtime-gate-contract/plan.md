---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/042-release-gate-read-side-consume-contract/spec.md"
  - "specs/043-policy-engine-typed-runtime-gate-contract/spec.md"
---

# 实施计划：043-policy-engine-typed-runtime-gate-contract

## 目标

把 `policy engine` 中的 runtime-gate consume seam 收口到 shared typed contract，确保 `evaluate_persisted_session_policy(...)` 与 `_runtime_gate_override(...)` 不再直接消费 raw `release_gate_verdict` dict。

## 架构摘要

- **One typed policy consume seam**：`policy engine` 通过 shared typed runtime-gate snapshot 读取 pass/degraded/missing/malformed 状态。
- **Reuse existing contract**：优先复用 `042` 的 `release_gate_read_contract.py`，只在必要时补强 helper，不再新建第二套 gate 解释层。
- **Policy semantics stay fixed**：本 work item 只收敛 consume seam，保持现有 `matched_policy_rules`、`decision_result` 与 risk 语义不变。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/043-policy-engine-typed-runtime-gate-contract/*` | 冻结 043 正式边界、任务拆解与 handoff |
| Shared runtime-gate helper | `src/watchdog/services/brain/release_gate_read_contract.py` | 在 042 基础上补齐 policy engine 所需的 typed runtime-gate consume surface |
| Policy engine | `src/watchdog/services/policy/engine.py` | 只通过 typed contract 读取 release-gate state，不再手工解释 raw dict |
| Contract tests | `tests/test_watchdog_policy_engine.py` | 锁定 typed pass / missing / malformed / partial 的 fail-closed 纪律 |

## 边界纪律

- 043 不得新增新的 policy 规则、schema、persistence、manifest、archive metadata 或 query facade。
- 043 不得把测试 helper 整理或 e2e 改造拔高成主目标。
- 043 只收敛 `policy engine` consume seam，不回到 refresh/read-side consumer/platform 设计面。

## 依赖顺序

1. **先冻结 formal docs 与 043 work item 元数据**
   - 明确 043 只做 typed runtime-gate policy contract；
   - 明确它不扩 policy surface、schema 或平台层。
2. **再写失败测试锁定 policy seam**
   - 先证明当前 policy engine 仍直接消费 raw verdict dict；
   - 先锁定 malformed / partial runtime-gate evidence 必须 fail closed。
3. **再补 shared helper 与 policy engine 收口**
   - 优先复用 042 已有 helper；
   - 让 `_runtime_gate_override()` 与相关 evidence 写入逻辑只消费 typed snapshot。
4. **最后更新 handoff**
   - 固定后续任何 policy/runtime gate consumer 都必须复用同一 typed contract。

## 分阶段计划

### Phase 1：冻结 043 formal docs、任务分解与执行元数据

交付内容：

- `specs/043-policy-engine-typed-runtime-gate-contract/spec.md`
- `specs/043-policy-engine-typed-runtime-gate-contract/plan.md`
- `specs/043-policy-engine-typed-runtime-gate-contract/tasks.md`
- `specs/043-policy-engine-typed-runtime-gate-contract/task-execution-log.md`
- `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/*`

### Phase 2：写失败测试锁定 typed runtime-gate policy contract

交付内容：

- `tests/test_watchdog_policy_engine.py`

### Phase 3：补齐 typed runtime-gate helper 与 policy engine 收口

交付内容：

- `src/watchdog/services/policy/engine.py`
- `src/watchdog/services/brain/release_gate_read_contract.py`
- `tests/test_watchdog_policy_engine.py`

### Phase 4：更新执行日志与 handoff 摘要

交付内容：

- `specs/043-policy-engine-typed-runtime-gate-contract/task-execution-log.md`
- `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/execution-plan.yaml`
- `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/runtime.yaml`
- `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/resume-pack.yaml`
- `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/latest-summary.md`

## 测试计划

- `tests/test_watchdog_policy_engine.py`
  - 锁定 policy engine 通过 typed runtime-gate contract 处理 pass / degraded / missing / malformed / partial evidence
- `tests/test_long_running_autonomy_doc_contracts.py`
  - 锁定总实施计划与 canonical work item 元数据同步

## 主要风险与应对

### 风险 1：把 typed contract 收口变成 policy 改写

应对：

- 红测只锁 consume seam 和 fail-closed 纪律；
- 保持现有 `matched_policy_rules`、`decision_result`、`why_escalated` 语义不变。

### 风险 2：scope 滑向测试平台整理

应对：

- 把 fixture helper、e2e 改造、测试平台化明确列为非目标；
- 只交付 policy engine seam 收口与必要 contract tests。

## 验收口径

只有当以下条件同时满足，043 才算完成：

1. `policy engine` 已通过 shared typed runtime-gate contract 读取 release-gate state；
2. `propose_execute` 路径对 missing / malformed / partial runtime-gate evidence 继续 fail closed；
3. `report:resident_default` 默认态未被误伤；
4. 未引入新的 policy、schema、manifest、persistence 或测试平台。
