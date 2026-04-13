# 任务分解：031-session-spine-events-projection-read-surface

> 对应规格：`specs/031-session-spine-events-projection-read-surface/spec.md`
>
> 对应计划：`specs/031-session-spine-events-projection-read-surface/plan.md`

## Task 31.1 冻结 031 formal docs 与读面切换边界

- **任务编号**：T311
- **状态**：已完成（2026-04-13）
- **目标**：把 031 从总实施计划中拆成 canonical execution work item，并写清 Session events projection 的范围与非目标。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/031-session-spine-events-projection-read-surface/spec.md`
  - `specs/031-session-spine-events-projection-read-surface/plan.md`
  - `specs/031-session-spine-events-projection-read-surface/tasks.md`
- **可并行**：否
- **验收标准**：
  1. 已明确 031 只做读面切换，不回头补 030 写面；
  2. 已明确 persisted spine 在 031 中只保留 compatibility fallback；
  3. 已明确 approval inbox 与 audit query 也属于 031 范围。
- **验证**：人工审阅 formal docs 与总实施计划的 Task 2 边界一致。
- **完成情况**：031 已正式建为独立 work item，下一执行入口固定为 `T312`。

## Task 31.2 写失败测试锁定 projection 来源优先级

- **任务编号**：T312
- **状态**：已完成（2026-04-13）
- **目标**：用失败测试锁定 Session events 必须成为 stable read surface 的默认来源。
- **文件**：
  - `tests/test_watchdog_session_spine_projection.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/test_watchdog_ops.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 Session events 优先于 persisted spine；
  2. 覆盖 approval inbox、memory anomaly、human override、notification status 来自 Session projection；
  3. 旧 persisted spine 只在 migration gap 时作为 fallback。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_api.py`
  - `uv run pytest -q tests/test_watchdog_ops.py -k session`
- **完成情况**：已补齐红灯测试，锁定 Session events 对 persisted spine 的读优先级，以及 approval inbox / memory anomaly / human override / notification status 的统一投影来源。

## Task 31.3 实现 Session events projection reader 与 compatibility fallback

- **任务编号**：T313
- **状态**：已完成（2026-04-13）
- **目标**：在 `session_spine` 服务层实现 events-first 的 projection reader，并把 persisted spine 收窄为 fallback。
- **文件**：
  - `src/watchdog/services/session_spine/store.py`
  - `src/watchdog/services/session_spine/projection.py`
  - `src/watchdog/services/session_spine/service.py`
  - `src/watchdog/services/session_service/service.py`
- **可并行**：否
- **验收标准**：
  1. `session / progress / facts / approval_queue` 可由 Session events 物化；
  2. memory degrade/conflict 当前态可从 Session projection 读取；
  3. compatibility fallback 只在事件缺口时触发。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_projection.py`
- **完成情况**：`session / progress / facts` 已优先由 Session events 物化，persisted spine 仅在 session events 缺口时作为 compatibility fallback。

## Task 31.4 重接 stable API、approval inbox 与 audit query

- **任务编号**：T314
- **状态**：已完成（2026-04-13）
- **目标**：让 stable session queries、approval inbox 与 audit path 统一走 Session query facade。
- **文件**：
  - `src/watchdog/api/session_spine_queries.py`
  - `src/watchdog/services/audit/service.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/test_watchdog_audit.py`
  - `tests/test_watchdog_ops.py`
- **可并行**：否
- **验收标准**：
  1. stable API contract 不变；
  2. approval inbox 与 session query 共享同一 projection 来源；
  3. audit query 不再优先读 persisted spine / legacy approvals。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_ops.py`
  - `uv run pytest -q tests/test_watchdog_audit.py`
- **完成情况**：stable API contract 保持不变，approval inbox 与 audit query 已收敛到同一 Session query / Session event 读口径。

## Task 31.5 完成 031 验证并交接下一 work item

- **任务编号**：T315
- **状态**：已完成（2026-04-13）
- **目标**：跑完整体验证并写清 handoff，使后续 work item 可直接消费 Session projection。
- **文件**：
  - `tests/test_watchdog_session_spine_projection.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/test_watchdog_audit.py`
  - `tests/test_watchdog_ops.py`
  - `specs/031-session-spine-events-projection-read-surface/task-execution-log.md`
- **可并行**：否
- **验收标准**：
  1. 031 所需测试全部通过；
  2. formal docs 与执行日志已更新到最终状态；
  3. handoff 明确后续 Goal Contract / Recovery 只消费 Session projection，不再重改读面主路径。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_ops.py`
  - `uv run pytest -q tests/test_watchdog_audit.py`
- **完成情况**：031 所需验证已全部通过，handoff 已明确后续 Goal Contract / Recovery 仅消费 Session projection，不再回切 persisted spine 主读路径。

## 整体验收

- 031 是长时运行自治一期的“Task 2”，只负责把 `session_spine` 读面切到 Session events projection。
- 031 完成后，stable query surface、approval inbox 与 audit query 应优先消费 Session projection，而不是 persisted spine / legacy approvals。
- 031 不新增新的 canonical 写面，不实现 Goal Contract、Recovery、Brain、Memory Hub 或 Feishu 正式能力。
