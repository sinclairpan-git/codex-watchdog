---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/040-release-gate-report-material-contract-and-hash-unification/spec.md"
---

# Release Gate Artifact Refresh / Rebuild Contract — 功能规格说明

## 概述

`041-release-gate-artifact-refresh-and-rebuild-contract` 是在 `WI-040` 完成后追加的第十二个正式执行 work item。它不再扩新的 release gate consume path，也不再扩新的 report material/hash 算法，而是把 `release_gate_report` 的 refresh、archive rebuild 与 fixture regeneration 正式化成唯一 operator contract。

041 的目标不是“再包一层脚本”，而是把当前 handoff 中已经明确的纪律落成正式工作流：

> `frozen inputs -> single refresh command -> generate report via shared material contract -> loader-valid output`

它只消费已经冻结的边界：

- `037` 的 release gate hard-blocker：runbook/script、样本窗口、`label_manifest`、artifact archive 都是正式 blocking inputs；
- `039` 的 shared loading API / evidence bundle contract，要求后续入口不得手写 parse/validate；
- `040` 的 shared report material/hash contract，要求后续 refresh / rebuild / regeneration 不得复制 `_stable_report_hash(...)` 或局部 `report_seed`。

它同时吸收两组外部约束：

- **Hermes Agent 专家边界**：041 必须是“单一 refresh 命令 + runbook + contract test”，不能再次引入新的 metadata 平台、manifest 或第二真相。
- **Anthropic Manager 专家边界**：041 应被定义成 refresh workflow contract，而不是宽泛 orchestration；输入、输出、成功态和 fail-closed 条件都要明确，但不应扩大到新的 schema/审计模型。

因此，041 的首要目标不是新增 release gate 能力，而是把 report refresh / rebuild 这条 operator 路径收口成唯一正式入口。

## 功能需求

- **FR-4101**：系统必须存在单一正式命令入口负责 `release_gate_report` 的 refresh、archive rebuild 与 fixture regeneration。operator 不得再通过分散脚本步骤、手工改 JSON 或局部 helper 完成这条链路。
- **FR-4102**：refresh 命令只能复用现有 `scripts/generate_release_gate_report.py`、`src/watchdog/services/brain/release_gate_report_material.py` 与 `src/watchdog/services/brain/release_gate_loading.py`。不得新增第二套 report 构造、hash/material 计算或 loader 校验逻辑。
- **FR-4103**：refresh 命令必须把输入边界写清楚，至少覆盖：`certification_packet_corpus`、`shadow_decision_ledger`、`label_manifest`、输出 report 路径/fixture 路径，以及生成责任人元数据。缺任一正式输入时必须 fail closed。
- **FR-4104**：refresh 生成出的 `release_gate_report` 必须能被 shared loader 直接接受；若输出 report 在 schema、canonical hash、runtime governance metadata 或正式输入上发生漂移，系统必须拒绝并显式失败，不得产生“部分刷新成功”的软通过语义。
- **FR-4105**：runbook 必须正式记录 refresh 命令的输入、输出、成功态与失败纪律，明确禁止人工编辑 JSON、手工猜 `report_hash`、绕过 shared helper 或跳过 loader 校验。
- **FR-4106**：041 不得新增 machine-readable refresh manifest、独立 archive metadata store、额外审计模型、release gate policy 变化、report schema 变化、evidence bundle 变化或 ops/read-side surface 变化。

### 用户故事 1：operator 需要一个唯一的 refresh / rebuild 入口

operator 需要在刷新 fixture、重建 archive 或重生成报告时，使用一个正式入口，而不是手动拼步骤。

场景 1：operator 提供冻结的 packets、shadow runs、label manifest 与输出路径，refresh 命令生成唯一有效的 `release_gate_report`。

场景 2：任一输入缺失或漂移时，refresh 命令直接失败，不能继续产出看起来可用的报告。

### 用户故事 2：后续 refresh 不能再分叉 hash/material 语义

后续 work item 可能需要重生成 fixture 或重建 report archive，但它们不能再重新定义 hash/material 规则。

场景 1：refresh 命令生成出的 `report_id/report_hash` 与 shared helper 完全一致。

场景 2：shared loader 立即接受 refresh 输出；如果不接受，则 refresh 本身视为失败。

## 非目标

- 不在 041 中新增 refresh manifest、archive metadata model 或查询/审计平台。
- 不在 041 中改变 release gate policy、`release_gate_report` schema、evidence bundle 或 read-side surface。
- 不在 041 中引入新的 report material/hash 算法；040 的 shared helper 已是唯一来源。
