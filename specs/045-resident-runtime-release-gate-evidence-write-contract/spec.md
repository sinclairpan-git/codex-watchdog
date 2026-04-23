---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/044-policy-engine-typed-validator-consume-contract/spec.md"
---

# Resident Runtime Release-Gate Evidence Write Contract — 功能规格说明

## 概述

`045-resident-runtime-release-gate-evidence-write-contract` 是在 `WI-044` 完成后追加的第十六个正式执行 work item。它不再扩新的 read-side、policy consume seam、参数命名整理或 e2e 平台，而是把 resident runtime 中剩余的 `release_gate_verdict + release_gate_evidence_bundle` 写侧组装收口成 shared write-side contract。

045 要解决的是当前仍停留在 orchestrator 内联拼装层的 write-side seam：

> `decision trace + validator verdict + release-gate verdict + optional loaded artifacts -> shared write-side contract -> canonical runtime evidence`

它只消费已经存在且冻结的边界：

- `039` 的 release-gate loading / evidence bundle contract；
- `042` 的 release-gate read-side consume contract；
- `043` / `044` 的 policy engine consume seam typed contract；
- 当前 resident runtime 的 decision evidence surface。

它同时吸收两组对抗约束：

- **Hermes Agent 专家边界**：045 必须只收口 `_decision_evidence_for_intent()` 里的 release-gate write-side 组装，不滑向参数命名整理或测试平台化。
- **Anthropic Manager 专家边界**：045 必须让正式 report path 与 report load failure fallback 复用同一 shared write-side helper；保持现有 evidence shape，不新增 schema、manifest、persistence 或 workflow 层。

因此，045 的首要目标不是重写 release gate，而是把 resident runtime 的 release-gate evidence 组装从 orchestrator 内联逻辑收口成单一正式 contract。

## 功能需求

- **FR-4501**：resident runtime 必须通过 shared write-side contract 组装 runtime decision evidence 中的 `release_gate_verdict` 与 `release_gate_evidence_bundle`；`_decision_evidence_for_intent()` 不得继续直接手工拼装这两个字段。
- **FR-4502**：shared write-side contract 必须同时覆盖正式 report path 与 report load failure fallback，并保持两条路径输出的 canonical evidence shape 稳定。
- **FR-4503**：045 不得改变现有 `release_gate_verdict` / `release_gate_evidence_bundle` 字段名、结构、read-side surface、policy semantics 或 runtime degrade taxonomy；它只收敛写侧组装 seam。
- **FR-4504**：045 不得新增新的 policy、schema、manifest、archive metadata、query facade、refresh workflow、parameter rename campaign 或测试平台层；shared helper 也不得顺手接管 `decision_trace`、`validator_verdict` 或其他 intent evidence 组装。
- **FR-4505**：测试可以复用现有 release-gate typed models 与 shared helper，但不得把 golden-path/e2e 断言整理作为 045 主目标。

### 用户故事 1：resident runtime 需要唯一 release-gate evidence 写侧 contract

resident runtime 会在 decision evidence 中写入 `release_gate_verdict` 与可选 `release_gate_evidence_bundle`，但不应该在 orchestrator 内维护两套拼装逻辑。

场景 1：正式 report path 下，write-side contract 输出现有完整 evidence bundle。

场景 2：report load failure fallback 下，write-side contract 继续输出现有 fallback bundle surface，而不是散落在 orchestrator 内联构造。

### 用户故事 2：写侧收口不能影响读侧/策略侧 contract

后续 read-side 与 policy engine 已经依赖现有 evidence shape。

场景 1：045 完成后，read-side consumer 与 policy engine 不需要额外适配。

场景 2：任何新的 resident runtime producer 都必须复用 shared write-side contract，而不是复制 `ReleaseGateEvidenceBundle(...)` 拼装代码。

## 非目标

- 不在 045 中修改 read-side、policy engine、e2e/golden-path 或 parameter naming。
- 不在 045 中修改 release-gate report schema、evidence bundle schema、manifest、persistence model 或新的 workflow。
- 不在 045 中引入新的第二真相或测试平台。
