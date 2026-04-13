# 执行日志：031-session-spine-events-projection-read-surface

> 对应规格：`specs/031-session-spine-events-projection-read-surface/spec.md`
>
> 对应任务：`specs/031-session-spine-events-projection-read-surface/tasks.md`

## 2026-04-13

- 完成 `T311`：已把总实施计划中的 `Task 2` 正式拆成 `WI-031`，并补齐 canonical `spec.md`、`plan.md`、`tasks.md`。
- 已将总实施计划回链到 `specs/031-session-spine-events-projection-read-surface/`，避免继续把 Task 2 仅保留在总计划中。
- 当前尚未进入产品实现；下一执行入口固定为 `T312`。
- 当前边界已冻结为：
  - `session_spine` stable read surface 优先消费 Session events projection；
  - 024 的 persisted spine 只保留 compatibility fallback；
  - approval inbox 与 audit query 一并切到 Session query facade；
  - 不回头补 030 的 canonical 写面，也不提前实现 Goal Contract / Recovery / Brain / Memory Hub。
