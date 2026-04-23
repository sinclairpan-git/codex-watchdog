---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/getting-started.zh-CN.md"
  - "docs/plans/2026-04-05-codex-live-control-bridge.md"
  - "specs/023-codex-client-routing-template/spec.md"
---

# 实施计划：023-codex-client-routing-template

## 目标

在已完成 `010-022` stable session spine 的基础上，把工程从“语义面可接入”推进到“现场集成可直接套模板接入”：runtime 侧聚焦真实 Codex 客户端接缝，watchdog 侧聚焦 Feishu 路由模板与配置参数收敛。

## 架构摘要

- **Reuse existing bridge**：真实 Codex 客户端只允许建立在现有 `CodexAppServerBridge + transport + protocol` 之上，不再新开旁路。
- **Fallback-first**：真实桥接不可用时，`LocalCodexClient` / `NoOpCodexClient` 必须继续兜底。
- **Template-over-runtime**：023 交付的是 Feishu 路由模板、示例与配置约束，不是飞书或 Feishu 内部运行时代码。
- **Stable-route reuse**：所有 Feishu 模板都必须复用 `010-022` 已冻结的 stable Watchdog HTTP route。
- **Explicit prerequisites**：网络地址、Token 策略、Codex/Feishu 样例接口都要作为显式输入项写进文档和模板，而不是隐藏假设。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| runtime-side Codex Client | `src/a_control_agent/services/codex/client.py`, `src/a_control_agent/services/codex/app_server_bridge.py`, `src/a_control_agent/services/codex/protocol.py`, `src/a_control_agent/services/codex/stdio_transport.py` | 明确真实 Codex 客户端能力边界、bridge 调用路径与降级语义 |
| runtime-side Route Binding | `src/a_control_agent/main.py`, `src/a_control_agent/api/tasks.py`, `src/a_control_agent/api/recovery.py`, `src/a_control_agent/api/approvals.py` | 把 client / bridge 配置挂到现有 API 与审核链路，统一错误与审计语义 |
| Feishu Template | `examples/codex_watchdog_client.py`, `README.md`, `docs/getting-started.zh-CN.md`, `config/examples/watchdog.env.example` | 提供查询/控制/审批路由模板、配置变量与接入说明 |
| 验证 | `tests/test_codex_local_client.py`, `tests/test_codex_app_server_bridge.py`, `tests/test_a_control_agent.py`, `tests/integration/test_feishu_integration_spine.py` | 锁住真实客户端接缝、降级路径与 Feishu 模板可用性 |

## 依赖顺序

1. **先冻结边界与输入项**
   - 定稿 023 的 scope、外部前提、路由矩阵与非目标。
2. **再补 runtime 侧真实 Codex 客户端接缝**
   - 先把 client / bridge / protocol 的能力与降级语义理顺。
3. **再接 runtime 侧 API 与审计**
   - 确保控制动作、审批回写与 thread 读取统一走同一条 bridge 链路。
4. **最后补 Feishu 路由模板、示例与文档**
   - 用 stable route 编出模板，并明确配置参数与现场替换点。

## 分阶段计划

### Phase 1：冻结真实客户端与模板边界

交付内容：

- `specs/023-codex-client-routing-template/*`
- 外部前提清单
- Feishu 路由矩阵

关键原则：

- 不扩 stable session spine scope
- 不把飞书 runtime 混进当前工作项
- 对缺失外部样例保持显式占位

### Phase 2：收敛 Codex client / bridge 接缝

交付内容：

- 真实 Codex client 接口与 bridge 行为收敛
- fallback / degrade 规则
- 相关单测

关键原则：

- 所有控制动作继续走 `CodexAppServerBridge`
- 默认保留 `LocalCodexClient` / `NoOpCodexClient`
- 错误语义、审批回写与审计统一

### Phase 3：接 runtime 侧 API 并补 Feishu 模板

交付内容：

- Codex runtime service API 与 bridge 的显式绑定
- Feishu 查询/控制/审批路由模板
- 环境变量与项目路由策略说明

关键原则：

- Feishu 模板只消费 stable HTTP routes
- 不写 Feishu 仓库内运行时代码
- `project_id`、URL、Token 都必须模板化

### Phase 4：文档、示例与状态收口

交付内容：

- README / getting-started / config example
- 最小 smoke / integration 验证
- `.ai-sdlc` 推进到 023 active state

关键原则：

- 文档必须回答“还差哪些外部输入”
- 示例要能直接指导接入而非只展示单一 API
- 状态记录与 formal docs 保持一致

## 测试计划

### Codex Client / Bridge

- `tests/test_codex_local_client.py`
- `tests/test_codex_app_server_bridge.py`

覆盖：

- 本地 client 发现与降级
- bridge 读线程、起 turn、steer、审批回写
- bridge 不可用或配置缺失时的稳定行为

### Codex runtime service API

- `tests/test_a_control_agent.py`

覆盖：

- tasks / recovery / approvals 对真实 bridge 的绑定
- 错误与审计语义
- native thread 与 bridge 路径共存

### Feishu Template / Integration

- `tests/integration/test_feishu_integration_spine.py`

覆盖：

- 查询进展/卡点/facts 的模板调用路径
- 继续推进与审批类模板调用路径
- Feishu 模板继续复用 stable reply / action contract

## 主要风险与应对

### 风险 1：为了接真实 Codex 客户端，再造一套旁路协议

应对：

- 只允许扩现有 `CodexAppServerBridge + protocol + transport`
- 在任务与测试中显式锁住这条边界

### 风险 2：Feishu 模板与 stable route 脱节

应对：

- 模板仅调用 `010-022` 已冻结的 stable HTTP routes
- integration 验证至少覆盖查询、控制、审批三个类别

### 风险 3：外部前提缺失导致工作项悬空

应对：

- 把网络地址、Token 策略、接口样例列为显式模板参数
- 文档写清“哪些是当前仓库已交付，哪些需要部署方提供”

## 脚手架备注

- 当前环境的 `ai-sdlc workitem init` 无法直接生成 023 formal docs。
- 直接原因已复现为：`ai_sdlc.core.workitem_scaffold.WorkitemScaffolder` 默认把模板目录解析到 `.venv/lib/python3.11/templates`，随后触发 `template not found: .../spec-template.md`。
- 因此 023 的 `spec.md / plan.md / tasks.md` 采用与 canonical direct-formal 一致的目录边界手工落到 `specs/023-codex-client-routing-template/`，并把失败原因保留在本工作项结果摘要中。

## 验收口径

只有当以下条件同时满足，023 才算进入完成态：

1. 真实 Codex 客户端接缝与 fallback 语义已经收敛到既有 bridge 边界。
2. Codex runtime service 的相关 API 已明确绑定 client / bridge，而不是隐式占位。
3. Feishu 路由模板已覆盖查询、控制、审批三类典型消息。
4. README、getting-started、示例与配置文件已经写清 URL / Token / `project_id` 路由策略。
5. `.ai-sdlc` 已从 022 完成态切换到 023 active state，且 formal docs / checkpoint / resume-pack 不再互相指向旧 work item。
