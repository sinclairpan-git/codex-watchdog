---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/024-resident-supervision-session-spine-persistence/spec.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
---

# Session Spine 读面切换到 Session Events Projection — 功能规格说明

## 概述

`031-session-spine-events-projection-read-surface` 是长时运行自治一期的第二个正式执行 work item。它从总实施计划中拆出“Task 2”，只负责一件事：

> 把当前 `session_spine` 的稳定读面、approval inbox 与审计读取口径，从 024 的 persisted spine / legacy approval 兼容层，切换为 030 建立好的 `Session Service` canonical events projection。

031 的边界同样要收得很窄。它只负责读面来源切换，不再回头补 030 的写真源，也不提前把 `Goal Contract`、`Recovery Transaction`、`Brain`、`Memory Hub` 或 `Feishu` 控制面塞进来。

## 功能需求

- **FR-3101**：031 必须让 `session_spine` stable read surface 优先从 `Session Service` canonical events 派生 `session / progress / facts / approval_queue`，而不是继续把 024 的 persisted spine 当成最终真相。
- **FR-3102**：024 的 `SessionSpineStore` 在 031 中只能保留兼容回填与 migration gap 兜底角色；当对应 session 的 canonical events 已足以物化 projection 时，读面不得再优先返回旧 persisted snapshot。
- **FR-3103**：031 必须把 `approval inbox`、session 级 `approval_queue`、notification status 与 human override status 全部收敛到同一套 Session projection / query facade，不得继续分别读取 legacy approvals truth 或 side-effect-only 状态。
- **FR-3104**：031 必须允许从 Session events projection 读出 `memory_unavailable_degraded`、`memory_conflict_detected` 与最近原因，使 audit query、release gate evidence 与后续 packet builder 可以直接消费 canonical memory anomaly 事实。
- **FR-3105**：031 必须明确区分 stable `session_id` 与投影层 `thread_id / native_thread_id`：`session_id` 继续服务于 Session events 与写面关联，stable route 对外返回的 `thread_id` contract 不得因投影切换而回退。
- **FR-3106**：`src/watchdog/services/audit/service.py` 与 `src/watchdog/api/session_spine_queries.py` 必须改为优先读 Session query facade，不得再把 raw persisted spine / legacy approvals 直接拼装成审计或稳定查询结果。
- **FR-3107**：031 必须保持 010-024 既有 stable route contract 兼容；OpenClaw 模板、session query API 与 approval inbox API 的返回形状不得因底层投影来源切换而破坏调用方。
- **FR-3108**：当 Session events projection 尚未覆盖某个历史 session 所需字段时，系统可以短暂回退到 persisted spine / legacy facade，但必须把回退行为限制为 compatibility path，而不是默认读取顺序。
- **FR-3109**：031 完成后，后续 Goal Contract、Recovery、Brain 与 Memory Hub work items 必须能只依赖 Session projection / query facade 读取稳定事实，而不需要再次直连 raw task query 或 persisted spine 老结构。

### 用户故事 1：稳定读面直接返回 Session events 派生结果

operator 与 OpenClaw 模板需要继续通过 `get_session / get_progress / why_stuck / explain_blocker / facts` 读取稳定视图，但底层真相不能再停留在 024 的 snapshot store。

场景 1：某 session 已拥有完整的 `decision / approval / notification / command lease / memory anomaly` canonical events 时，stable route 直接返回由这些 events 派生的 projection。

场景 2：若某个旧 session 还缺少部分 canonical event，系统只在该缺口范围内回退到 persisted spine，而不是继续默认读旧 snapshot。

### 用户故事 2：approval inbox 与审计查询不再分叉

长期运行系统不能一边让 session query 读 persisted spine，一边让 approval inbox 或审计继续读旧 approvals truth。

场景 1：approval inbox 与 session 内 `approval_queue` 来自同一套 Session projection。

场景 2：审计查询能直接看到 memory degrade/conflict、human override 与 notification receipt 的 canonical 投影，而不需要跨多个旁路 store 重新拼接。

### 用户故事 3：后续 work item 可以只依赖 projection facade

Goal Contract、Recovery、Brain 与 Memory Hub 都需要一套统一事实面作为输入。

场景 1：后续 work item 只调用 Session query facade 就能拿到当前 session、approval、memory anomaly 与 human override 状态。

场景 2：后续实现不需要再把 024 的 persisted spine 当成长期真相层，只把它视作迁移兼容 cache。

## 非目标

- 不在 031 中新增任何新的 Session event 写入点；030 已冻结 canonical 写面，031 只消费它。
- 不在 031 中实现完整 `Goal Contract`、`Recovery Transaction`、`Brain`、`Memory Hub` 检索或 `Feishu` 控制面。
- 不在 031 中重写 OpenClaw 模板、审批响应 API 或 delivery worker 的外部协议。
- 不在 031 中删除 024 的 persisted spine 文件结构；031 只降低其读取优先级并保留兼容回填。
