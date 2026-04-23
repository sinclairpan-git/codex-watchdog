---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
---

# 实施计划：031-session-spine-events-projection-read-surface

## 目标

让 `session_spine`、approval inbox 与 audit query 的稳定读面统一切到 `Session Service` events projection，同时把 024 的 persisted spine 降级为兼容回填层，而不是继续充当最终真相来源。

## 架构摘要

- **Read from canonical events first**：031 默认读取 030 已建立的 `Session Service` canonical events，并在读时物化 `session / progress / facts / approval_queue / memory anomaly`。
- **Compatibility fallback only**：024 的 persisted spine 仍保留，但只在历史迁移缺口时作为兼容 cache；新读面不再以它为 truth source。
- **Single query facade**：approval inbox、session query 与 audit query 共享同一套 projection builder / query facade，避免再维护多条平行读取路径。
- **Contract stays stable**：外部 stable API 与 Feishu 模板继续保持原有返回形状，031 只切底层来源，不改调用方协议。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Projection read model | `src/watchdog/services/session_spine/projection.py` | 从 Session events 派生 `SessionProjection`、`TaskProgressView`、approval inbox 与 memory anomaly 当前态 |
| Query facade | `src/watchdog/services/session_spine/service.py` | 优先读取 Session events，必要时兼容回退 persisted spine |
| Compatibility cache | `src/watchdog/services/session_spine/store.py` | 保留 024 persisted spine 结构，但只承担 fallback / migration cache |
| Stable API | `src/watchdog/api/session_spine_queries.py` | 所有 stable session / approval inbox 查询统一经过 Session query facade |
| Audit read path | `src/watchdog/services/audit/service.py` | 优先读 Session projection，而不是旧 persisted spine / approvals 旁路 |
| Verification | `tests/test_watchdog_session_spine_projection.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_ops.py` | 锁定 projection 来源优先级、contract 兼容与 audit 非回归 |

## 边界纪律

- 031 只切换读面来源，不修改 030 的 canonical 写入契约。
- 031 不补新的 Session events，也不把 approval / notification / human override writer 再做一轮重构。
- 031 不把 Goal Contract、Recovery、Brain 或 Memory Hub 正式实现混入当前 work item。
- 031 不删除 024 的 persisted spine 数据文件；直到迁移兼容窗口关闭前，它都作为 fallback 存在。

## 依赖顺序

1. **先冻结 formal docs 与读面边界**
   - 把“读 Session events 优先、persisted spine 兼容回退”写进 formal docs；
   - 明确 approval inbox / audit query 也在 031 范围内一起切换。
2. **再写失败测试锁来源优先级**
   - 先证明现状仍默认读 persisted spine / legacy approvals；
   - 锁住 memory anomaly、human override、notification status 不能继续来自旁路。
3. **再实现 projection reader 与 query facade**
   - 从 Session events 物化 stable session/progress/facts/approvals；
   - 只在事件缺口时回退到 024 persisted spine。
4. **再重接 stable API 与 audit path**
   - `session_spine_queries.py`、approval inbox 与 `audit/service.py` 都改为优先读 Session query facade；
   - 确认外部 contract 不变。
5. **最后跑回归并交接**
   - 锁住 stable route contract、audit query 与 ops 非回退；
   - handoff 明确下一 work item 不再回头修补读面来源。

## 分阶段计划

### Phase 1：冻结 031 formal docs 与 projection 优先级

交付内容：

- `specs/031-session-spine-events-projection-read-surface/spec.md`
- `specs/031-session-spine-events-projection-read-surface/plan.md`
- `specs/031-session-spine-events-projection-read-surface/tasks.md`

关键原则：

- 先把“events-first, persisted-fallback-only”写死；
- 明确 approval inbox 与 audit query 也属于同一个读面切换批次。

### Phase 2：写失败测试锁定 projection 来源

交付内容：

- `tests/test_watchdog_session_spine_projection.py`
- `tests/test_watchdog_session_spine_api.py`

关键原则：

- 先锁旧 persisted spine 默认优先级必须退出主路径；
- memory anomaly、human override、notification status 进入 projection 断言。

### Phase 3：实现 Session events projection reader

交付内容：

- `src/watchdog/services/session_spine/projection.py`
- `src/watchdog/services/session_spine/service.py`
- `src/watchdog/services/session_spine/store.py`

关键原则：

- projection builder 直接消费 Session events；
- 兼容回退必须显式而且收窄。

### Phase 4：切换 stable API 与 audit query

交付内容：

- `src/watchdog/api/session_spine_queries.py`
- `src/watchdog/services/audit/service.py`
- `tests/test_watchdog_ops.py`

关键原则：

- 对外 contract 不变；
- 读面来源统一，不再各自拼装。

### Phase 5：整体验证与 handoff

交付内容：

- `tests/test_watchdog_session_spine_projection.py`
- `tests/test_watchdog_session_spine_api.py`
- `tests/test_watchdog_ops.py`
- `specs/031-session-spine-events-projection-read-surface/task-execution-log.md`

关键原则：

- 031 结束时，读面切换必须成立；
- 下一 work item 可以专注 Goal Contract / Recovery，而不是回头继续清理 persisted spine 读主路径。

## 测试计划

- `tests/test_watchdog_session_spine_projection.py`
  - Session events 优先、persisted fallback only、approval / memory anomaly 投影
- `tests/test_watchdog_session_spine_api.py`
  - stable API 继续返回既有 contract，但底层来源改为 Session projection
- `tests/test_watchdog_ops.py`
  - ops / audit 路径仍可读取稳定事实，不因 projection 切换回退

## 主要风险与应对

### 风险 1：读面仍悄悄优先返回 024 persisted spine

应对：

- 先写失败测试锁旧顺序；
- 在 service 层显式区分 `events_projection` 与 `persisted_spine_fallback`。

### 风险 2：approval inbox、audit query 与 session query 三条读取链继续分叉

应对：

- 031 把 approval inbox 与 audit 一并纳入；
- 强制它们都走同一 Session query facade。

### 风险 3：迁移期历史 session 无法完整投影

应对：

- 保留 persisted spine fallback；
- 把 fallback 收口为 compatibility path，不允许继续成为默认真相。

## 验收口径

只有当以下条件同时满足，031 才算完成：

1. `session_spine` stable read surface 已优先消费 Session events projection；
2. persisted spine 只作为兼容回退存在，不再是默认读主路径；
3. approval inbox、memory anomaly、human override、notification status 与 audit query 已统一走 Session query facade；
4. stable API / Feishu 模板 contract 不回退；
5. 下一 work item 可以直接基于 Session projection 继续 Goal Contract / Recovery，不再回头改读面主路径。
