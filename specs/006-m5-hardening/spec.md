---
related_doc:
  - "codex-watchdog-prd.md"
---

# M5 加固与 PRD 交付缺口（非飞书 / 非 Feishu 渠道）— 功能规格说明

## 概述

在 **不实现飞书机器人、不实现 Feishu 渠道插件** 的前提下（PRD §3.2），补齐 PRD **§18 M5** 与 **§14.3 可观测性**、**§19.1 对 Codex app-server 的对接准备**、**§22 部分交付物** 中仍可由本仓库独立完成的部分。

## 功能需求

- **FR-401**：Codex runtime service 与 Watchdog 均暴露 **`GET /metrics`**（Prometheus 文本格式），至少包含：任务数、审计中可聚合的 handoff / resume / steer / 审批相关事件计数（与 PRD §14.3「任务数、卡顿次数、自动 steer 次数、审批数、恢复次数」对齐；其中「卡顿」以 Watchdog 侧 `steer_injected` 等可观测动作为代理，若审计无对应 action 则记 0）。
- **FR-402**：`POST .../resume` 先将任务置为 **`resuming`**，再置为 **`running`**，并保留审计（PRD §6.1、FR-302）。
- **FR-403**：提供 **工作区活动摘要**（基于任务 `cwd` 的文件系统扫描：最近修改时间、变更文件数上限），供后续与「真卡顿」判别结合；**不**执行任意 shell、不扫描全机。
- **FR-404**：提供 **Codex 下游客户端占位**（Protocol + 默认空实现），明确未来对接 Codex app-server 的边界，不包含真实协议调用。
- **FR-405**：补充 **PRD §16.2** 类集成测试（双服务 TestClient / 同进程链），覆盖：创建任务 → 查询 → evaluate→steer（可 mock）、审批登记→决策、关键路径错误码（不含飞书）。
- **FR-406**：交付 **OpenAPI JSON 导出脚本** 与 **Feishu 侧调用 Watchdog 的示例脚本**（仅 HTTP，无飞书），满足 PRD §22 中「API 文档」「集成适配脚本」的最低可交付形态。

### 用户故事 1：运维可抓取指标

场景 1：Prometheus / 监控在拉取 `GET /metrics` 时能获得任务数与关键审计事件计数。

场景 2：`/healthz` 行为保持不变。

### 用户故事 2：状态机与对接边界

场景 1：调用 `resume` 后持久化状态中经历 `resuming` 再到 `running`。

场景 2：Codex 相关能力通过 `codex_client` 占位注入，默认不发起外呼。

### 用户故事 3：验收与文档产物

场景 1：`pytest` 包含 `tests/integration/`，跑通至少一条端到端链。

场景 2：仓库内可通过脚本生成 OpenAPI JSON，并存在 `examples/` 下仅依赖 `httpx` 的 Watchdog 调用示例。

## 非目标（本工作项不做什么）

- 不实现飞书、不实现 Feishu 插件、不要求真实 Codex app-server 在线。
- 不实现 PRD §9.3.8 SSE 事件流（保留后续工作项）。
- 不将 Repo 扫描作为唯一「卡顿」真值（仍以现有 stuck 逻辑为准）。
