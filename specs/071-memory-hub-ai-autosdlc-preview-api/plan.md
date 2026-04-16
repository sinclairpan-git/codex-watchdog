# Plan：071-memory-hub-ai-autosdlc-preview-api

## 目标

把 `MemoryHubService.ai_autosdlc_cursor()` 从 service-only preview adapter 补成 app-level 可调用能力，同时保持 preview contract 默认关闭。

## 实施边界

1. 先写 app-level failing tests，锁住默认 disabled 与显式 enabled 两条 route contract。
2. 再补最小 wiring：setting、`create_app()` 注入、受控 API route。
3. 最后同步 `ai_sdlc` 状态，吸收 Hilbert / Gauss 对抗评审后关闭工单。

## 验证

- `uv run pytest -q tests/test_watchdog_memory_cursor_api.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_hub.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`

