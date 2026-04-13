# 执行日志：031-session-spine-events-projection-read-surface

> 对应规格：`specs/031-session-spine-events-projection-read-surface/spec.md`
>
> 对应任务：`specs/031-session-spine-events-projection-read-surface/tasks.md`

## 2026-04-13

- 完成 `T311`：已把总实施计划中的 `Task 2` 正式拆成 `WI-031`，并补齐 canonical `spec.md`、`plan.md`、`tasks.md`。
- 已将总实施计划回链到 `specs/031-session-spine-events-projection-read-surface/`，避免继续把 Task 2 仅保留在总计划中。
- 完成 `T312`：补齐失败测试，锁定 Session events projection 对 persisted spine 的默认读优先级，并覆盖 approval inbox、memory anomaly、human override、notification status 的来源约束。
- 完成 `T313`：在 `session_spine` 服务层落地 events-first projection reader，新增 Session event facts 物化逻辑，并把 persisted spine 收窄为 compatibility fallback。
- 完成 `T314`：stable session queries、approval inbox 与 audit query 已统一接到 Session query facade；audit query 现在会把 `session_service.json` 中的 Session events 纳入 canonical audit 视图。
- 完成 `T315`：已完成整体验证与 handoff 收口，后续 work item 应仅消费 Session projection，不再回切 persisted spine / legacy approvals 主读路径。
- 当前边界已冻结为：
  - `session_spine` stable read surface 优先消费 Session events projection；
  - 024 的 persisted spine 只保留 compatibility fallback；
  - approval inbox 与 audit query 一并切到 Session query facade；
  - 不回头补 030 的 canonical 写面，也不提前实现 Goal Contract / Recovery / Brain / Memory Hub。
- 本次验证结果：
  - `uv run pytest -q tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_api.py` 通过；
  - `uv run pytest -q tests/test_watchdog_ops.py -k session` 通过；
  - `uv run pytest -q tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_ops.py` 通过（53 passed）；
  - `uv run pytest -q tests/test_watchdog_audit.py` 通过（3 passed）。
