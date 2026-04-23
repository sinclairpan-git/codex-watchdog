---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "docs/architecture/codex-watchdog-full-product-loop-design.md"
  - "specs/022-stable-session-facts/spec.md"
  - "specs/023-codex-client-routing-template/spec.md"
---

# 常驻监督与 Session Spine 持久化 — 功能规格说明

## 概述

在 `023` 完成真实 Codex 客户端接缝与 Feishu 路由模板之后，仓库已经具备：

- runtime 侧真实事实读取与最小动作执行能力；
- watchdog 侧 stable session spine / facts / explanations / action surfaces；
- Feishu 可直接消费的稳定路由模板。

但当前 `Watchdog(B)` 仍主要依赖：

- 查询时临时向 A 拉取事实并构建 read bundle；
- 启动时一次性 background supervision；
- 没有 resident projection runtime；
- 没有 canonical 持久化 session spine；
- 没有为后续 policy / execution / delivery 准备好的单调版本与顺序语义。

`024-resident-supervision-session-spine-persistence` 的唯一目标固定为：

> 建立常驻的 session projection runtime 与可恢复的 canonical session spine 持久化层，让后续策略引擎、自动执行与主动投递都建立在稳定事实面之上，而不是继续依赖查询时临时拼装。

## 功能需求

- **FR-2401**：024 必须在 `Watchdog(B)` 内新增常驻 `Projection Worker`，持续从 `Codex runtime service` 拉取或接收事实变化，而不是只在应用启动时执行一次监督逻辑。
- **FR-2402**：024 必须落一套 canonical session spine 持久化层，至少能稳定保存：
  - `session_id`
  - `project_id`
  - `native_thread_id`
  - 当前稳定状态
  - 当前进展摘要
  - `FactRecord[]`
  - `pending_approval_count`
  - `last_progress_at`
  - `last_refreshed_at`
- **FR-2403**：024 必须为每个 session 引入单调递增的 `session_seq`，用于同一 session 内的稳定顺序语义；后续 replay / restore 不得产生重复或回退。
- **FR-2404**：024 必须为持久化事实快照引入稳定的 `fact_snapshot_version`；当 canonical 事实面未发生变化时，不得仅因轮询刷新而伪造新的快照版本。
- **FR-2405**：024 必须把以下稳定状态纳入 canonical session spine，而不是继续只依赖 raw task status：
  - `blocked`
  - `paused`
  - `awaiting_approval`
  - `planning`
  - `coding`
  - `recovery_pending`
- **FR-2406**：024 必须为查询层补齐 freshness 语义，至少允许 read bundle 判断：
  - 当前快照是否新鲜
  - 当前快照是否为上一次持久化结果
  - 上次成功刷新时间
- **FR-2407**：024 完成后，stable session 查询面必须优先读取 canonical 持久化 session spine，而不是继续在 read API 内直接向 runtime 侧临时拼装核心 session 视图。
- **FR-2408**：024 必须支持 restart / replay / restore；`Watchdog(B)` 重启后，resident projection runtime 必须能从持久化 spine 恢复，并继续推进 `session_seq` 与 `fact_snapshot_version`，而不是从空白态重新开始。
- **FR-2409**：024 可以继续复用既有 `projection.py / service.py / facts.py` 构建逻辑，但不得新增一条绕过 session spine 的 raw/legacy 旁路给后续策略或查询层使用。
- **FR-2410**：024 不得引入策略引擎；不得实现 `auto_execute_and_notify / require_user_decision / block_and_alert` 的正式判定。
- **FR-2411**：024 不得引入 `DecisionEnvelope / ApprovalEnvelope / NotificationEnvelope` 的持久投递链，也不得引入 `delivery_outbox / receipt / webhook`。
- **FR-2412**：024 不得实现 Feishu webhook、Feishu 渠道 runtime 或用户响应回流；这些都留给后续 work items。
- **FR-2413**：024 必须补齐单元测试、API 测试与最小集成验证，至少锁住：
  - resident runtime 持续刷新
  - `session_seq` 单调性
  - `fact_snapshot_version` 稳定性
  - restart / restore 语义
  - stable query route 继续返回既有 contract
- **FR-2414**：024 完成后，必须使后续 `WI-2` 可以在不直连 Codex runtime service raw query 的前提下，直接消费 canonical session spine 与事实快照。
- **FR-2415**：024 的 canonical session spine 必须持有后续 resident orchestrator 所需的最小判定字段，不得把这些字段继续留在 query-time 临时拼装层。至少包括：
  - `session_state`
  - `attention_state`
  - `pending_approval_count`
  - `approval_queue`
  - `available_intents`
  - `activity_phase`
  - `summary`
  - `files_touched`
  - `context_pressure`
  - `stuck_level`
  - `last_progress_at`
- **FR-2416**：024 必须冻结一条承接纪律：后续 policy / execution / delivery resident loop 只能消费 persisted spine 与其派生快照，不得把 Feishu 上下文、人工记忆或 query-time raw 拼装结果当成流程真值。
- **FR-2417**：024 的 restart / restore 语义必须允许后续 resident orchestration checkpoint 独立持久化并在重启后继续工作；即使 resident orchestration 本身在后续 WI 中实现，也不得因为 024 的存储边界设计导致“重启后重新从空白态认识项目”。

### 用户故事 1：watchdog 侧可以持续维护会话真值，而不是查询时临时拼装

Watchdog 需要作为完整产品闭环的决策中心，不能每次都在 query API 内临时向 A 拉数据再现算 session view。

场景 1：resident projection runtime 持续刷新某个项目会话，并把结果持久化为 canonical session spine 快照。

场景 2：`get_session / get_progress / why_stuck / explain_blocker / facts` 之类稳定读面优先从持久化 spine 读取，而不是各自直连 raw data source。

### 用户故事 2：服务重启后，canonical session spine 能恢复

长期运行时，Watchdog 可能被重启、升级或异常退出，但不能把会话顺序语义与已观察事实全部丢掉。

场景 1：服务重启后，resident runtime 从已持久化 spine 恢复，再继续推进 `session_seq` 与 `fact_snapshot_version`。

场景 2：重复刷新同一事实时，不会因 restart 而制造新的假快照版本。

### 用户故事 3：后续策略引擎可以直接消费稳定事实面

后续 `WI-2` 需要基于 canonical facts 做策略判定。

场景 1：策略引擎可以直接读取某个 session 当前的 persisted snapshot，而不用重复接 raw A query。

场景 2：同一 session 的事实快照有清晰顺序、freshness 与恢复语义，适合后续 decision key 与审计使用。

场景 3：后续 resident orchestrator 可以只根据 persisted spine 检测“决策意义变化”与“用户可感知 progress 变化”，而不需要依赖 Feishu 记忆项目上下文。

## 非目标

- 不实现策略引擎，不定义 `human_gate / hard_block` 的运行时代码。
- 不实现自动执行、人工升级或阻断告警。
- 不实现 `DecisionEnvelope / ApprovalEnvelope / NotificationEnvelope` 的 outbox 或 webhook。
- 不实现 Feishu 宿主 runtime、Feishu 渠道 runtime 或用户响应回流。
- 不把 resident supervision 扩成 delivery / retry / receipt 系统。
- 不在 024 内直接实现 `progress_summary` 主动推送；024 只负责把它所依赖的 persisted truth source 冻结好，实际推送由后续 resident orchestrator 承担。
- 不在本工作项中引入第二套 session spine、第二套状态机或 raw query 旁路。
