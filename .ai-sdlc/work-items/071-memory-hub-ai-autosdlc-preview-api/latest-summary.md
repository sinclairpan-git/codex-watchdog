# Development Summary

Status: completed
Total Tasks: 5
Completed Tasks: 5
Halted Tasks: 0
Total Batches: 5
Completed Batches: 5
Last Committed Task: T715

## Notes

- `WI-071` 目标是把 `MemoryHubService.ai_autosdlc_cursor()` 从 service-only preview adapter 补成真实 app-level callable surface，同时保持 preview contract 默认关闭。
- 当前已完成：
  - 新增 `memory_preview_ai_autosdlc_cursor_enabled` setting，并通过 `build_memory_preview_contract_overrides()` 收敛 runtime preview enablement；
  - `create_app()` 现在会把 preview override 注入 `MemoryHubService.from_data_dir(...)`；
  - 新增受 `Bearer` token 保护的 `POST /api/v1/watchdog/memory/preview/ai-autosdlc-cursor` route；
  - 新增 app-level tests，覆盖默认 disabled 与 opt-in enabled 两条调用路径。
- 双专家最终复核结论：
  - Hilbert：无 `P0/P1/P2`，可关闭 `WI-071`；
  - Gauss：无 `P0/P1/P2`，app-level gap 已关闭。

## Verification

- `uv run pytest -q tests/test_watchdog.py tests/test_watchdog_memory_cursor_api.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_hub.py` -> `26 passed in 0.67s`
- `uv run python -m ai_sdlc verify constraints` -> `Constraints OK`
- `uv run python -m ai_sdlc status` -> expected after checkpoint sync: `linked_wi_id=071-memory-hub-ai-autosdlc-preview-api`, `current_stage=completed`, `current_branch=codex/071-memory-hub-ai-autosdlc-preview-api`, `next_work_item_seq=72`

## Handoff

- `WI-071` 只补 preview adapter 的 app wiring，不改变 Brain/provider 主链，也不改变 default-off preview policy。
- 后续应进入 `WI-072`，继续排查剩余 repo-local owner gap，而不是回退到 `065` 的 service-only 讨论。
