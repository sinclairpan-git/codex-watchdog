---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/042-release-gate-read-side-consume-contract/spec.md"
---

# Policy Engine Typed Runtime-Gate Contract — 功能规格说明

## 概述

`043-policy-engine-typed-runtime-gate-contract` 是在 `WI-042` 完成后追加的第十四个正式执行 work item。它不再扩新的 `release_gate_report`、refresh workflow 或 read-side consumer，而是把 `policy engine` 里剩余的 runtime-gate consume seam 收口成 shared typed contract。

043 要解决的不是“给 policy 多包一层 helper”，而是把当前仍停留在 `dict[str, Any]` 级别的 gate 解释面收掉：

> `canonical release-gate evidence -> shared typed runtime-gate contract -> policy engine override`

它只消费已经冻结的边界：

- `039` 的 shared loading/evidence bundle contract；
- `042` 的 shared read-side consume contract，要求新的 consumer 不得再回退成 raw dict；
- 当前 `policy engine` 的规则面、decision result、matched rule 命名与 fail-closed 原则。

它同时吸收两组对抗约束：

- **Hermes Agent 专家边界**：043 必须只收口 `policy engine` 这一处生产 seam，不能滑向测试工厂整理或 e2e 平台化改造。
- **Anthropic Manager 专家边界**：043 必须让 `evaluate_persisted_session_policy()` 与 `_runtime_gate_override()` 消费 typed runtime-gate snapshot；malformed / partial / absent runtime-gate evidence 要 fail closed，但不新增 policy、schema、persistence 或 manifest。

因此，043 的首要目标不是改变 policy，而是让 `policy engine` 不再手工解释原始 `release_gate_verdict` 字典。

## 功能需求

- **FR-4301**：`policy engine` 必须通过 shared typed runtime-gate contract 读取 `release_gate` evidence；`evaluate_persisted_session_policy(...)` 与 `_runtime_gate_override(...)` 不得继续直接消费 raw `release_gate_verdict` dict。
- **FR-4302**：typed contract 必须区分至少四种状态：`pass`、`degraded`、`missing`、`malformed/partial`。`policy engine` 在 `propose_execute` 路径中必须对后三者统一 fail closed。
- **FR-4303**：对于 non-default formal report，缺 bundle、partial bundle 或 malformed runtime-gate evidence 时，policy engine 必须视为 runtime gate 不合格；`report:resident_default` 默认态不得被误当成 formal report drift/blocker。
- **FR-4304**：043 不得改变现有 `matched_policy_rules`、`decision_result`、`risk_class`、`why_escalated` 语义；它只收敛 consume seam，不重写 policy surface。
- **FR-4305**：043 不得新增新的 release-gate policy、report schema、evidence bundle schema、query facade、测试平台、refresh workflow、manifest 或 archive metadata 层。
- **FR-4306**：测试可以复用 042 的 shared read contract 或 043 内收紧的 helper，但不得把 shared fixture/test factory 作为 043 的主目标。

### 用户故事 1：policy engine 需要唯一 runtime-gate consume seam

policy engine 需要判断 `propose_execute` 是否具备 formal runtime gate，但不应该自己维护 `release_gate_verdict` 的字典语义。

场景 1：runtime-gate snapshot 为正式 pass 时，policy engine 保持现有 allow path。

场景 2：runtime-gate evidence 缺失、malformed、partial 或 degraded 时，policy engine 保持现有 block/human-gate 语义，但不得再通过 raw dict 漏过。

### 用户故事 2：typed contract 不能误伤 resident default path

当前系统仍存在 `report:resident_default` 默认态；它不是 formal report，但也不是 schema drift。

场景 1：`report:resident_default` 继续沿现有默认路径被 policy engine 处理，不被误判为 formal report bundle 缺失。

场景 2：只要进入 formal report 语义，bundle 缺失或结构不完整就必须 fail closed。

## 非目标

- 不在 043 中新增 release-gate policy、matched rule、decision result 或 blocker taxonomy。
- 不在 043 中新增测试平台、fixture factory work item、e2e 重构、manifest 或新的 read/query facade。
- 不在 043 中修改 `release_gate_report` schema、evidence bundle schema、refresh workflow 或 persistence model。
