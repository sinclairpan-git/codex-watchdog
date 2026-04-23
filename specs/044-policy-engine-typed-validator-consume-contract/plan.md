---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/043-policy-engine-typed-runtime-gate-contract/spec.md"
  - "specs/044-policy-engine-typed-validator-consume-contract/spec.md"
---

# 实施计划：044-policy-engine-typed-validator-consume-contract

## 目标

把 `policy engine` 与 resident runtime 中的 validator consume seam 收口到 shared typed contract，确保相关 consumer 不再直接消费 raw `validator_verdict` dict。

## 架构摘要

- **One typed validator consume seam**：`policy engine` 与 resident runtime 通过同一个 typed validator snapshot 读取 pass/degraded/missing/malformed 状态。
- **Reuse existing validator model**：优先复用 `DecisionValidationVerdict`，只在必要时补 shared read helper，不再新建第二套 validator model。
- **Policy semantics stay fixed**：本 work item 只收敛 consume seam，保持现有 `matched_policy_rules`、`decision_result` 与 risk 语义不变。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/044-policy-engine-typed-validator-consume-contract/*` | 冻结 044 正式边界、任务拆解与 handoff |
| Shared validator helper | `src/watchdog/services/brain/validator_read_contract.py` | 统一 typed 解析 `validator_verdict` evidence，只提供 read contract，不新增第二层归一化 helper |
| Policy engine | `src/watchdog/services/policy/engine.py` | 只通过 typed validator contract 读取 validator state，不再手工解释 raw dict |
| Resident runtime | `src/watchdog/services/session_spine/orchestrator.py` | 只把 auto-execute/runtime gate 判断改为复用同一 typed validator contract |
| Contract tests | `tests/test_watchdog_policy_engine.py` / `tests/test_watchdog_session_spine_runtime.py` | 锁定 typed pass / missing / malformed / partial 的 fail-closed 纪律 |

## 边界纪律

- 044 不得新增新的 policy 规则、schema、persistence、manifest、archive metadata 或 query facade。
- 044 不得把 release-gate write-side 收口、fixture helper 整理或 e2e 改造拔高成主目标。
- 044 只收敛 validator consume seam，不回到 release-gate runtime evidence 写侧或测试平台设计面。

## 依赖顺序

1. **先冻结 formal docs 与 044 work item 元数据**
   - 明确 044 只做 typed validator consume contract；
   - 明确它不扩 policy surface、schema 或平台层。
2. **再写失败测试锁定 validator seam**
   - 先证明当前 policy engine / resident runtime 仍直接消费 raw validator dict；
   - 先锁定 malformed / partial validator evidence 必须 fail closed。
3. **再补 shared helper 与 consumer 收口**
   - 优先复用 `DecisionValidationVerdict`；
   - 让 `policy engine` 与 resident runtime 的相关判断只消费 typed snapshot。
4. **最后更新 handoff**
   - 固定后续任何 validator consumer 都必须复用同一 typed contract。

## 分阶段计划

### Phase 1：冻结 044 formal docs、任务分解与执行元数据

交付内容：

- `specs/044-policy-engine-typed-validator-consume-contract/spec.md`
- `specs/044-policy-engine-typed-validator-consume-contract/plan.md`
- `specs/044-policy-engine-typed-validator-consume-contract/tasks.md`
- `specs/044-policy-engine-typed-validator-consume-contract/task-execution-log.md`
- `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/*`

### Phase 2：写失败测试锁定 typed validator consume contract

交付内容：

- `tests/test_watchdog_policy_engine.py`
- `tests/test_watchdog_session_spine_runtime.py`

### Phase 3：补齐 typed validator helper 与 consumer 收口

交付内容：

- `src/watchdog/services/brain/validator_read_contract.py`
- `src/watchdog/services/policy/engine.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `tests/test_watchdog_policy_engine.py`
- `tests/test_watchdog_session_spine_runtime.py`

### Phase 4：更新执行日志与 handoff 摘要

交付内容：

- `specs/044-policy-engine-typed-validator-consume-contract/task-execution-log.md`
- `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/execution-plan.yaml`
- `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/runtime.yaml`
- `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/resume-pack.yaml`
- `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/latest-summary.md`

## 测试计划

- `tests/test_watchdog_policy_engine.py`
  - 锁定 policy engine 通过 typed validator contract 处理 pass / degraded / missing / malformed / partial evidence
- `tests/test_watchdog_session_spine_runtime.py`
  - 锁定 resident runtime 不再直接把 raw validator dict 当作 auto-execute 真值
- `tests/test_long_running_autonomy_doc_contracts.py`
  - 锁定总实施计划与 canonical work item 元数据同步

## 主要风险与应对

### 风险 1：把 typed validator contract 收口变成 policy 改写

应对：

- 红测只锁 consume seam 和 fail-closed 纪律；
- 保持现有 `matched_policy_rules`、`decision_result`、`why_escalated` 语义不变。

### 风险 2：scope 滑向 release-gate write-side 整理

应对：

- 把 release-gate write-side helper、fixture helper、e2e 改造明确列为非目标；
- 只交付 validator consume seam 收口与必要 contract tests。

## 验收口径

只有当以下条件同时满足，044 才算完成：

1. `policy engine` 与 resident runtime 已通过 shared typed validator contract 读取 `validator_verdict`；
2. `propose_execute` 路径对 missing / malformed / partial validator evidence 继续 fail closed；
3. resident runtime 不再保留 validator raw dict 第二真相；
4. 未引入新的 policy、schema、manifest、persistence 或测试平台。
