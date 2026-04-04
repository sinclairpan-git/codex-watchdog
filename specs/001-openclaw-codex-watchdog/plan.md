---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 实施计划：OpenClaw × Codex 双机会话监管系统

## 目标与范围

交付 A-Control-Agent（A 机）、Watchdog / Policy Engine（B 机）、A/B HTTPS+Token 通信、统一数据模型与审计，以及 OpenClaw 侧调用 Watchdog 的集成方式。不包含飞书机器人与 OpenClaw 渠道插件本身（PRD §3.2）。

## 技术栈

- **来源**：`.ai-sdlc/profiles/tech-stack.yml`
- **后端**：Python 3.11+，建议 FastAPI（PRD §15.1）；Watchdog 同栈可选。
- **协议**：A/B 间 HTTPS，内网/Tailscale，全链路 Bearer Token（PRD §9、§13）。

## 架构要点

- B 仅通过 A-Control-Agent 业务 API 监管，不直连 Codex 原始协议、不控 A 机桌面（PRD §4）。
- 状态以结构化字段为准；自动动作必须可审计（PRD §4.1、§13.3）。

## 阶段与产物

| 阶段 | 目标 | 主要产出 |
|------|------|----------|
| M1 | 查询闭环 | Agent 最小 API + Watchdog progress 代理 + 鉴权骨架 |
| M2 | 监管 | stuck 检测、steer、循环检测、审计日志 |
| M3 | 审批 | 审批模型、风险分级、自动/人工路径 |
| M4 | 恢复 | handoff 摘要、resume/新线程策略 |
| M5 | 加固 | `/healthz`、指标、集成测试与模拟器（PRD §16–§17） |

## 宪章响应

- **持久化决策**：技术选型与接口契约落在仓库（本 plan、contracts、tasks）。
- **契约优先验证**：API 与数据模型以 contract 与自动化测试校验后再收口。
- **可追溯**：需求条目映射到 PRD 章节与 FR 编号。

## 仓库布局（建议）

见 PRD §15.2：`src/api/`、`src/services/`（`codex_client`、`task_manager`、`a_client`、`status_analyzer` 等）、`models/`、`storage/`。
