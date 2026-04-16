# Plan：066-task-state-model-closure

1. 冻结 `WI-066` owner 边界与 formal docs。
2. 先写红测，锁定 PRD 正式 `status` / `phase` 枚举与历史实现态 normalize 语义。
3. 实现 `TaskStore`、`/api/v1/tasks`、bridge/client/recovery 写回的统一 normalize 与 fail-closed 校验。
4. 跑 `A-Control-Agent` / `Watchdog` 受影响 targeted 回归。
5. 回写 `ai_sdlc` 状态，并交给两个常驻对抗专家复审。
