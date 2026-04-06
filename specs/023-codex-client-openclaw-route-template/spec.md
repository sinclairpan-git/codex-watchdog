---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/getting-started.zh-CN.md"
  - "docs/plans/2026-04-05-codex-live-control-bridge.md"
  - "specs/010-openclaw-integration-spine/spec.md"
  - "specs/022-stable-session-facts/spec.md"
---

# 真实 Codex 客户端与 OpenClaw 路由模板 — 功能规格说明

## 概述

在 `010-022` 已经冻结 stable session spine、stable action/read surface 与 OpenClaw adapter 主闭环之后，当前剩余的工程缺口已经不在 Watchdog 的语义层，而在**真实接入层**：

- A 侧已经存在 `LocalCodexClient`、`NoOpCodexClient` 与 `CodexAppServerBridge`，但“真实 Codex 客户端”仍停留在最小协议面与 bridge 能力，缺少一个面向部署的明确接缝与错误/降级语义；
- B 侧已经存在 `examples/openclaw_watchdog_client.py` 与稳定 HTTP API，但还没有一套可直接给 OpenClaw 集成方复用的**查询/控制/审批路由模板**；
- `docs/getting-started.zh-CN.md` 已经把外部前提收敛到网络地址、Token 策略与 Codex/OpenClaw 接口样例，因此下一工作项应聚焦于“如何直接接起来”，而不是继续扩 stable contract。

023 的唯一目标固定为：

> 在不引入飞书渠道代码的前提下，补齐真实 Codex 客户端接缝与 OpenClaw 路由模板，使当前仓库从“稳定语义面已完成”推进到“可被外部系统直接按模板接入”。

## 功能需求

- **FR-2301**：023 必须在 A-Control-Agent 中明确“真实 Codex 客户端”边界，至少覆盖以下已存在能力的生产化接缝：
  - `thread/read`
  - `turn/start`
  - `turn/steer`
  - 审批请求登记与审批决策回写
- **FR-2302**：`LocalCodexClient` 与 `NoOpCodexClient` 必须继续保留为默认降级路径；即使未提供真实 bridge / transport 配置，服务也必须保持可启动、可读状态同步。
- **FR-2303**：真实 Codex 客户端不可绕过当前 `CodexAppServerBridge` 的 transport / audit / approval store 边界；不得再引入第二套并行控制链路。
- **FR-2304**：023 必须为 OpenClaw 集成方提供明确的路由模板，覆盖至少三类消息：
  - 查询类
  - 控制类
  - 审批类
- **FR-2305**：OpenClaw 路由模板必须明确从“自然语言/命令语义”到 Watchdog stable route 的映射，不得再让接入方自行猜测 `project_id`、HTTP path、鉴权头与 reply envelope 结构。
- **FR-2306**：023 必须把 `project_id` 路由、`WATCHDOG_BASE_URL` / `WATCHDOG_API_TOKEN` 等接入参数收敛为模板化配置，而不是散落在示例代码与文档段落里。
- **FR-2307**：023 必须显式列出外部依赖前提：
  - A/B 网络地址
  - Token 策略
  - Codex app-server 接口样例
  - OpenClaw 侧命令/路由接口样例
  缺失前提时必须以“占位配置/模板参数”形式暴露，而不是隐式跳过。
- **FR-2308**：023 只落真实客户端接缝与路由模板，不得改写 `010-022` 已冻结的 stable session spine contract、reply_code 语义或 canonical routes。
- **FR-2309**：023 必须补齐针对真实 Codex 客户端接缝的测试与回归，包括：
  - client/bridge happy path
  - bridge 不可用时的降级路径
  - 审批回写与控制动作错误语义
- **FR-2310**：023 必须补齐针对 OpenClaw 路由模板的最小验证，至少确认模板可覆盖“查询进展 / 查询卡点 / 继续 / 审批”这四类典型消息。
- **FR-2311**：README、getting-started 与示例代码必须清楚说明：
  - 本仓库仍然不包含飞书机器人与 OpenClaw 插件运行时代码
  - 但已经给出可复用的接入模板与配置约束
- **FR-2312**：023 完成后，工程状态必须从“022 已完成但接入模板待补”推进到“023 已进入可执行实现态”，并在 `.ai-sdlc` 中体现为新的 active work item。

### 用户故事 1：A 机可以在真实 Codex bridge 与本地降级之间稳定切换

部署方希望在配置齐全时接入真实 Codex app-server，在未接通时仍保留本地采集与安全降级。

场景 1：配置 bridge 后，A-Control-Agent 通过统一 client / bridge 接缝执行 `thread/read`、`turn/start`、`turn/steer` 与审批回写。

场景 2：未配置或 bridge 不可达时，系统继续使用 `LocalCodexClient` / `NoOpCodexClient`，不会导致服务启动失败或状态接口失效。

### 用户故事 2：OpenClaw 集成方可以直接按模板对接 Watchdog

OpenClaw 集成方已经有消息入口，但不希望从 README、示例与 API 自己反向拼一套路由。

场景 1：给定 `WATCHDOG_BASE_URL`、`WATCHDOG_API_TOKEN` 与 `project_id` 路由规则后，可以按模板调用 Watchdog 的 stable query / action / approval route。

场景 2：模板中明确规定自然语言/命令到 HTTP route 的映射、鉴权头与响应处理方式。

### 用户故事 3：缺失外部前提时，系统能明确告诉接入方还差什么

当前仓库能推进 formal work item，但现场部署可能尚未提供网络地址、Token 规则或上游接口样例。

场景 1：文档明确把这些缺口列为模板参数或待确认项，而不是混在实现逻辑里。

场景 2：接入方可以先按占位模板完成工程对接，再在拿到真实样例后替换配置。

## 非目标

- 不实现飞书机器人、OpenClaw 插件或 OpenClaw 上游仓库内的运行时代码。
- 不重写 `010-022` 已冻结的 Watchdog stable API contract。
- 不新增新的 session spine read/write 能力或 reply DTO。
- 不把真实 Codex 客户端实现扩成另一套独立控制平面。
- 不要求在本工作项中拿到所有外部样例后才允许创建 formal docs 与任务分解。
