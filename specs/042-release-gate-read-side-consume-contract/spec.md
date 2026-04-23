---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/040-release-gate-report-material-contract-and-hash-unification/spec.md"
  - "specs/041-release-gate-artifact-refresh-and-rebuild-contract/spec.md"
---

# Release Gate Read-Side Consume Contract — 功能规格说明

## 概述

`042-release-gate-read-side-consume-contract` 是在 `WI-041` 完成后追加的第十三个正式执行 work item。它不再扩新的 `release_gate_report` 生成、refresh 或 material/hash contract，而是把 read-side consumer 对 `release_gate_verdict` 与 `release_gate_evidence_bundle` 的消费方式正式收口成单一 typed contract。

042 要解决的不是“再加一个 DTO 文件”，而是把当前仍散落在 consumer 里的字段路径与嵌套假设收回到一处：

> `canonical decision evidence -> shared typed read contract -> ops / runtime read-side consumer`

它只消费已经冻结的边界：

- `039` 的 shared loading API / evidence bundle contract，要求后续 consumer 不得重新解释 `release_gate_report` 与 evidence bundle；
- `040` 的 report material/hash contract，要求 read-side 只能读取已经冻结的 `report_id / report_hash / input_hash` surface，不得重新计算；
- `041` 的 refresh / rebuild contract，要求后续 operator 路径只复用单一 refresh 命令，而不是再扩新的 platform surface。

它同时吸收两组对抗约束：

- **Hermes Agent 专家边界**：042 应该是 shared helper / typed model + 1-2 个现有 consumer 的收口，不能滑成“测试整理 work item”或新的 read platform。
- **Anthropic Manager 专家边界**：042 必须聚焦 read-side consume seam，优先消掉 `ops.py` 这类生产 read-side 的手工 dict 剥取；malformed / partial evidence 要 fail closed，但不新增 policy、schema、persistence 或 query facade。

因此，042 的首要目标不是新增 release gate 行为，而是让 read-side 解释面不再复制字段名、嵌套路径与降级纪律。

## 功能需求

- **FR-4201**：系统必须存在单一 shared typed helper / contract，用来从 canonical decision evidence 中解析 `release_gate_verdict` 与 `release_gate_evidence_bundle`。现有 read-side consumer 不得继续各自手工剥取字段。
- **FR-4202**：shared helper 必须保留 `report_id`、`report_hash`、`input_hash`、`release_gate_report_ref`、`certification_packet_corpus_ref`、`shadow_decision_ledger_ref`、`label_manifest_ref`、`generated_by` 与 `report_approved_by` 等正式 blocker metadata surface，禁止 consumer 自己重新拼装或裁剪字段路径。
- **FR-4203**：当 evidence 缺失、类型不对、结构不完整或 bundle 只部分存在时，read-side consume path 必须 fail closed：不能把 malformed payload 当成完整 blocker metadata，也不能把它当成 pass-qualified runtime evidence 继续使用。
- **FR-4204**：至少一个正式 read-side API consumer 和一个 runtime read-side consumer 必须改为只消费 shared helper，而不是直接读 evidence dict。042 的首批目标是 `src/watchdog/api/ops.py` 与当前 resident runtime 的 decision evidence 读取路径。
- **FR-4205**：042 不得新增新的 release gate policy、report schema、evidence bundle schema、persistence model、manifest、archive metadata、query facade、测试平台或 refresh workflow 变化。
- **FR-4206**：测试可以复用 042 新增的 shared read contract，但 042 不得把“测试工厂整理”单独拔高成新的 canonical work item；测试改动只能服务于正式 read-side contract 的 red/green 验证。

### 用户故事 1：ops 需要单一 blocker metadata 解释面

ops 侧需要把 release gate blocker 暴露给告警/审计接口，但不应该自己维护 evidence 嵌套路径。

场景 1：decision evidence 带有完整 `release_gate_verdict` 与 `release_gate_evidence_bundle` 时，ops 只通过 shared helper 读取 blocker metadata，并输出稳定字段。

场景 2：evidence bundle 缺失、结构损坏或只带局部字段时，ops 仍保留 blocker reason，但不会把残缺 bundle 当成完整 blocker metadata 继续透传。

### 用户故事 2：runtime 读取 pass qualification 时不能继续散落 dict 假设

resident runtime 需要判断当前 decision 是否具备 formal runtime gate evidence，但不应该继续靠 `isinstance(..., dict)` 和裸字段路径判断。

场景 1：shared helper 返回正式 pass-qualified verdict 时，runtime 可以继续沿现有链路判断 auto execute。

场景 2：evidence 结构漂移或 verdict/bundle 缺失时，runtime 只能按 fail-closed 处理，不能靠局部默认值继续视作 formal runtime gate。

## 非目标

- 不在 042 中新增 release gate policy、`release_gate_report` schema、evidence bundle schema 或 blocker taxonomy。
- 不在 042 中新增 query facade、ops read model、manifest、archive metadata store 或新的 read platform。
- 不在 042 中把测试 report factory / fixture builder 单独做成主目标；测试改动只服务正式 read-side contract。
