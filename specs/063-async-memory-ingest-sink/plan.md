# Plan：063-async-memory-ingest-sink

1. 冻结 `WI-063` owner 边界与 formal docs。
2. 先写 targeted tests，锁定 “enqueue first, drain later” 的异步边界。
3. 实现 durable queue store 与 ingest worker。
4. 调整 `create_app()` wiring 与后台 loop。
5. 运行 targeted / impacted 回归，并回写 `ai_sdlc` 状态与 residual risk。
