---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/043-policy-engine-typed-runtime-gate-contract/spec.md"
---

# Policy Engine Typed Validator Consume Contract — 功能规格说明

## 概述

`044-policy-engine-typed-validator-consume-contract` 是在 `WI-043` 完成后追加的第十五个正式执行 work item。它不再扩新的 release-gate write-side、测试整理或 e2e 平台，而是把 `policy engine` 与 resident runtime 中剩余的 `validator_verdict` consume seam 收口成 shared typed contract。

044 要解决的是当前仍停留在 raw dict 层的 validator gate 解释面：

> `canonical validator evidence -> shared typed validator contract -> policy engine / resident runtime`

它只消费已经存在且冻结的边界：

- `035` 引入的 `DecisionValidationVerdict` typed model；
- `043` 刚完成的 policy engine typed runtime-gate consume seam；
- 当前 `policy engine` 的规则面、decision result、matched rule 命名与 fail-closed 原则。

它同时吸收两组对抗约束：

- **Hermes Agent 专家边界**：044 必须只收口 validator consume seam，不能滑向 release-gate write-side 整理或测试平台化。
- **Anthropic Manager 专家边界**：044 必须让 `evaluate_persisted_session_policy()`、`_runtime_gate_override()` 与 resident runtime 的 auto-execute 判断消费 typed validator snapshot；malformed / partial / absent validator evidence 要 fail closed，但不新增 policy、schema、persistence 或 manifest。

因此，044 的首要目标不是重写 validator，而是让消费方不再手工解释原始 `validator_verdict` 字典。

## 功能需求

- **FR-4401**：`policy engine` 与 resident runtime 必须通过 shared typed validator contract 读取 `validator_verdict` evidence；相关 consumer 不得继续直接消费 raw `validator_verdict` dict。
- **FR-4402**：typed contract 必须区分至少四种状态：`pass`、`degraded`、`missing`、`malformed/partial`。`policy engine` 在 `propose_execute` 路径中必须对后三者统一 fail closed。
- **FR-4403**：resident runtime 只在 auto-execute / runtime-gate 判断这条读侧链路上复用同一套 typed validator 解释逻辑，不能保留第二真相，也不能顺手把 `orchestrator.py` 里其他 evidence 解释逻辑纳入 044。
- **FR-4404**：044 不得改变现有 `matched_policy_rules`、`decision_result`、`risk_class`、`why_escalated` 语义；它只收敛 consume seam，不重写 policy surface。
- **FR-4405**：044 不得新增新的 validator policy、schema、persistence、manifest、archive metadata、query facade、release-gate write-side helper 或测试平台层。
- **FR-4406**：测试可以复用 `DecisionValidationVerdict` 与新 shared helper，但不得把 e2e 断言整理或 fixture 平台作为 044 的主目标。

### 用户故事 1：policy engine 需要唯一 validator consume seam

policy engine 需要判断 `propose_execute` 是否具备 validator pass gate，但不应该自己维护 `validator_verdict` 的字典语义。

场景 1：validator snapshot 为合法 pass 时，policy engine 保持现有 allow path。

场景 2：validator evidence 缺失、malformed、partial 或 degraded 时，policy engine 保持现有 block 语义，但不得再通过 raw dict 漏过。

### 用户故事 2：resident runtime 不能保留第二套 validator 真值

resident runtime 会基于 persisted decision evidence 判断是否允许 auto execute。

场景 1：resident runtime 必须与 `policy engine` 一样通过同一个 typed validator contract 判断 pass / missing / malformed。

场景 2：validator dict 缺字段或结构损坏时，resident runtime 不能再把 `"status": "pass"` 当成有效放行条件。

## 非目标

- 不在 044 中新增 validator 规则、decision result 或 blocker taxonomy。
- 不在 044 中收口 release-gate write-side 组装、e2e 平台、fixture factory 或 golden-path 断言整理。
- 不在 044 中修改 persistence model、event schema、manifest 或新的 query facade。
