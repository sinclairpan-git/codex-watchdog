---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# OpenClaw × Codex 双机会话监管系统 — 功能规格说明

## 概述

在 A 机运行 Codex 与 A-Control-Agent、B 机运行 OpenClaw 与 Watchdog 的前提下，建立标准化 A/B 协议、任务与审批数据模型、自动 steer / handoff / resume 与 L0–L3 风险分级，使飞书侧可查询进展并处理卡顿与审批。需求真值以仓库根目录 `openclaw-codex-watchdog-prd.md`（V1.0）为准；本文将 PRD 拆解为可验收的功能需求与用户故事。

## 功能需求

- **FR-001**：系统应提供 A-Control-Agent 对外 API（创建任务、查询状态、steer、handoff、resume、审批列表与决策），且请求/响应符合 PRD §9 统一 envelope 与鉴权要求。
- **FR-002**：系统应持久化 `project_id` ↔ `thread_id` 及任务主状态、阶段、`context_pressure`、`stuck_level` 等字段，并与 PRD §6 状态模型一致。
- **FR-003**：Watchdog 应能轮询或订阅 A-Control-Agent，聚合进展并在 P95 约束内响应 OpenClaw 的查询类调用（PRD §10、§14）。
- **FR-004**：系统应按 PRD §8 默认阈值检测无进展卡顿，并依次触发记录、soft steer、飞书提醒、handoff/resume，且动作可审计。
- **FR-005**：系统应检测「等待下一步」与循环失败场景，并按 PRD §8.4 模板注入相应 steer。
- **FR-006**：当 `context_pressure` 达到 high/critical 时，系统应按 PRD §8.3 生成 handoff 摘要并执行 resume 或新线程续跑路径。
- **FR-007**：系统应对审批请求执行 L0–L3 分级（PRD §7），L0/L1 可自动处理，L2/L3 必须经飞书人工决策路径，且不得默认放行高风险操作。
- **FR-008**：A 不可达时，B 侧应返回明确的控制链路异常状态，不得伪装任务仍在运行（PRD §14.2）。
- **FR-009**：关键操作须写入审计日志（创建任务、steer、handoff、resume、自动/人工审批、风险判定等，PRD §13.3）。
- **FR-010**：应提供健康检查与基础指标（任务数、卡顿次数、steer 次数等，PRD §14.3），并支持模拟器/假事件流测试（PRD §16.3）。

### 用户故事 1：飞书侧查询开发任务进展

用户在飞书中通过 OpenClaw 查询指定 `project_id` 的任务摘要、阶段、最近改动与阻塞点。

场景 1：用户发送「现在进展」或带 `project_id` 的查询时，Watchdog 返回结构化进展（含 `status`、`phase`、`last_summary`、`files_touched`、阻塞与审批状态），OpenClaw 将其转写为自然语言。

场景 2：查询在约定时间内（成功标准：飞书侧响应小于 5 秒，PRD §2.2）完成；若 A 侧不可达，返回明确链路异常说明。

### 用户故事 2：Watchdog 对无进展卡顿的自动处理

Watchdog 根据 transcript/文件变更/命令输出等信号判断 stuck，并按升级策略自动 steer 或通知。

场景 1：连续满足「无新事件且无文件变更」超过 8 分钟时，系统自动注入一次 soft steer（PRD §5.2、§8.1）。

场景 2：持续无进展达到更高级阈值时，系统升级飞书提醒，并在满足条件时进入 handoff/resume 流程且全程留痕。

### 用户故事 3：审批分级与人工闭环

Codex 产生审批请求后，由 Watchdog 分级并决定自动通过或推送飞书待人工决策。

场景 1：L0/L1 请求在满足策略时可自动决策并记录审计日志。

场景 2：L2/L3 请求在飞书中精确展示命令、风险与备选方案，人工决策经 Watchdog 回传 A-Control-Agent 后继续执行。
