# Task Execution Log：072-memory-hub-preview-operator-readiness-docs

- 2026-04-17：初始化 `WI-072`，目标为把 `ai-autosdlc-cursor` preview route 的 operator 真值补成正式 env sample / getting-started / doc contract，而不是继续扩新的 runtime 语义。
- 2026-04-17：Hilbert 与 Gauss 对抗评审一致认定当前缺口为 `P2` operator-readiness gap，建议单独立 `WI-072` 收口。
- 2026-04-17：已补 `watchdog.env.example` 的 `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=false`，以及 `getting-started.zh-CN.md` 的启用方式、default-off 语义与最小 smoke test。
- 2026-04-17：已把 preview toggle / route / default-off 语义纳入 repo-local docs contract 守卫，后续文档漂移会直接被测试与 `ai_sdlc verify constraints` 捕获。
- 2026-04-17：本地验证通过后，Hilbert 与 Gauss 的 closeout review 均返回“无 `P0/P1/P2`，可关闭 `WI-072`”。
