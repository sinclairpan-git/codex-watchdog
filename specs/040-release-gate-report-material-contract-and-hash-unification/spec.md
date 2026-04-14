---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
---

# Release Gate Report Material / Hash Shared Contract — 功能规格说明

## 概述

`040-release-gate-report-material-contract-and-hash-unification` 是在 `WI-039` 完成后追加的第十一个正式执行 work item。它不再扩新的 release gate consume path，而是把 039 之后仍然残留的一处漂移风险正式收口：`release_gate_report` 的 report material、`report_id` seed 与 `report_hash` 计算仍分散在 generator script、loader 与测试辅助逻辑里。

040 的目标不是改变报告 schema 或放行规则，而是把“报告如何生成唯一 canonical material”这件事正式化：

> `frozen evidence inputs -> shared report material contract -> report_id/report_hash -> generator / fixture / loader`

它只消费已经冻结的边界：

- `035` 的 release gate runtime contract、runbook/script artifact 与 governance metadata；
- `037` 的 release blocker hard inputs 与 low-risk auto-decision fail-closed 语义；
- `039` 的 shared loading API / evidence bundle contract，要求后续入口不能再各自复制 report 解释逻辑。

它同时吸收两组外部约束：

- **Hermes Agent 专家边界**：`report_hash` material 与 `report_id` seed 不能在 script、loader、fixture refresh 或 test helper 中维护多份“看起来一样”的算法；必须只有一个共享定义。
- **Anthropic Manager 专家边界**：运行时需要区分“报告文件存在”“报告是由 canonical material 计算出来的”“loader 能证明当前 payload 与 canonical material 一致”这三个层次；缺任一层都不能视为治理面闭环。

因此，040 的首要目标不是再补新的 consume surface，而是先消掉 generation side 的 hash/material second truth。

## 功能需求

- **FR-4001**：系统必须存在单一 shared helper 负责 `release_gate_report` 的 canonical JSON material、`report_id` seed 与 `report_hash` 计算。generator script、loader、fixture refresh 与测试不得再各自维护本地版本。
- **FR-4002**：shared helper 必须明确 `report_hash` 的计算材料为“canonical report payload 去掉 `report_hash` 后的 JSON material”，并且这一定义要同时被 script 与 loader 复用，不能靠两份局部 helper 偶然保持一致。
- **FR-4003**：shared helper 必须把 `artifact_ref`、`sample_window`、`shadow_window`、`input_hash`、`generated_by`、`report_approved_by`、runtime governance metadata 与其他正式报告字段纳入 canonical material 约束；future refresh 不得私自增删 material 字段。
- **FR-4004**：generator script 产出的 `release_gate_report` 必须能被 shared loader 直接接受，并且 loader 重新计算出的 canonical hash 必须与报告内 `report_hash` 完全一致。
- **FR-4005**：040 不得改变既有 `release_gate_report` schema、`release_gate_evidence_bundle` surface、runtime degrade reason taxonomy、runbook blocking inputs 或 low-risk auto-decision 门槛。它只收口 report generation / hash material contract。
- **FR-4006**：future fixture refresh、report archive 重建或新入口如需生成/比对 `release_gate_report`，必须复用同一 shared helper，而不是复制 `_stable_report_hash(...)`、`report_seed` 或手写 canonical JSON 逻辑。

### 用户故事 1：operator 刷新 report fixture 时不想重新猜 hash 算法

operator 需要在更新 fixture、runbook 产物或 report archive 时，确保生成侧与加载侧还是同一份 contract。

场景 1：script 生成新的 `release_gate_report` 后，loader 不需要额外适配就能接受该报告。

场景 2：tests/fixtures 需要重生成时，只能通过 shared helper 对齐 `report_id` / `report_hash`，不能手改 JSON 后再猜哈希。

### 用户故事 2：后续入口不能再复制 report material 逻辑

后续 work item 可能需要刷新 report、重建 archive，或者对比 canonical material。

场景 1：新的 consumer 需要验证 `report_hash`，只能导入 shared helper。

场景 2：测试或脚本需要构造报告时，只能复用 shared material contract，不能本地定义第二套 `report_seed`。

## 非目标

- 不在 040 中新增新的 release gate policy、风险门槛或 blocker taxonomy。
- 不在 040 中改变 `release_gate_report` 对外 schema、evidence bundle 字段或 ops surfacing。
- 不在 040 中引入新的 report storage、archive index 或 metrics label 设计。
