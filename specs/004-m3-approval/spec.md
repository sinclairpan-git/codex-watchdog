---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# M3 审批能力 — 功能规格说明

## 概述

在 M1/M2 已具备任务与监管基础的前提下，本工作项交付 **审批对象持久化、L0–L3 风险分级、自动通过策略、审批查询与决策 API**（PRD §7、§9.3.6–9.3.7、§10.1.2、§18 M3）。飞书推送本身不在本仓库范围，以审计与 API 替代「提醒」真值。

## 功能需求

- **FR-201**：A-Control-Agent 应持久化审批对象字段与 PRD §7.2 一致（`approval_id`、`project_id`、`thread_id`、`risk_level`、`command`、`reason`、`alternative`、`status`、`requested_at` 等）。
- **FR-202**：系统应提供命令行/字符串到 **L0–L3** 的规则型分级器；L3 不得被默认自动通过（PRD §7、§17.2）。
- **FR-203**：对 **L0/L1** 在策略允许时自动 `approve` 并写审计；**L2/L3** 保持 `pending` 直至显式决策。
- **FR-204**：实现 `GET /api/v1/approvals`（支持 `status` 查询）与 `POST /api/v1/approvals/{approval_id}/decision`（PRD §9.3.6–9.3.7）。
- **FR-205**：Watchdog 暴露 `GET /api/v1/watchdog/approvals` 与 `POST /api/v1/watchdog/approvals/{approval_id}/decision`，代理 A 侧并统一 envelope（PRD §10.1.2）。
- **FR-206**：提供 `POST /api/v1/approvals`（或等价内部入口）用于登记新的审批请求（便于测试与后续 Codex 对接）。

### 用户故事 1：风险分级与自动通过

运维希望低风险命令无需人工确认即可继续。

场景 1：当命令被分级为 L0 且策略允许自动通过时，审批记录状态变为 `approved` 并写审计。

场景 2：当命令被分级为 L3 时，记录保持 `pending`，且不会自动通过。

### 用户故事 2：人工决策闭环

监管方希望对 L2 待办执行显式批准或拒绝。

场景 1：`POST .../decision` 传入 `approve` 后，状态变为 `approved` 并记录操作人。

场景 2：`reject` 时状态为 `rejected` 且保留原因字段。

### 用户故事 3：Watchdog 聚合查询

OpenClaw 侧需要统一入口列出待审批项。

场景 1：`GET /watchdog/approvals?status=pending` 返回与 A 侧一致的结构化列表。

场景 2：A 不可达时返回 `CONTROL_LINK_ERROR`，不伪造空列表为成功业务数据。
