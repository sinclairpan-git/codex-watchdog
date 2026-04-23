# Spec：071-memory-hub-ai-autosdlc-preview-api

## 背景

`WI-065` 已经在 `MemoryHubService` 内实现了 `ai_autosdlc_cursor()` preview adapter、请求/响应模型以及 targeted tests，但当前 app runtime 仍停留在 service-only：

- `src/watchdog/main.py` 通过 `MemoryHubService.from_data_dir(settings.data_dir)` 构建默认实例；
- runtime 没有任何 setting 可以把 `ai-autosdlc-cursor` preview contract 从 app 层启用；
- `src/watchdog/api/` 没有任何受控 route 可以调用该 adapter。

这导致仓库内“stage-aware preview adapter”只在测试里可达，不在真实 `create_app()` surface 内可达。

## 范围

### In Scope

- `src/watchdog/settings.py`
- `src/watchdog/main.py`
- `src/watchdog/api/`
- `tests/`
- `ai_sdlc` 工单文档与状态同步

### Out of Scope

- 不在本工单内改动 Brain/provider 主链；
- 不在本工单内改变 Memory Hub 默认 preview disabled 的策略；
- 不在本工单内引入新的 Session Service truth source；
- 不在本工单内新增除 `ai-autosdlc-cursor` 以外的 preview contract app wiring。

## Formal Source

- `specs/065-ai-autosdlc-preview-cursor/spec.md`
- `.ai-sdlc/work-items/065-ai-autosdlc-preview-cursor/latest-summary.md`
- `src/watchdog/services/memory_hub/service.py`
- `src/watchdog/services/memory_hub/models.py`
- `src/watchdog/main.py`

## 非 Owner 约束

- **FR-7101**：071 只补 `Memory Hub` preview adapter 的 app-level opt-in wiring，不扩大成 Brain orchestration owner。
- **FR-7102**：preview contract 仍须 default-off；未显式启用时，route 可以被调用，但返回结果必须保持 `enabled=false` 的 preview 语义。
- **FR-7103**：只能复用已存在的 `AIAutoSDLCCursorRequest` / `ContextQualitySnapshot` / `AIAutoSDLCCursorResponse` 语义，不重写 packet generation contract。

## 功能需求

- **FR-7104**：`Settings` 必须提供 `ai-autosdlc-cursor` preview adapter 的 app-level opt-in 开关。
- **FR-7105**：`create_app()` 必须把该 setting 注入 `MemoryHubService`，不再把 preview enablement 限制在测试 override。
- **FR-7106**：repo 必须新增一个受 `Bearer` token 保护的 app-level route，用于调用 `ai_autosdlc_cursor()`。
- **FR-7107**：该 route 在默认配置下必须返回 `enabled=false` 的正式 preview 响应；在 opt-in 开启后必须返回真实 stage-aware packet。
- **FR-7108**：repo-local 测试必须覆盖默认 disabled 与 opt-in enabled 两条 app-level 路径，防止 capability 再次退化回 service-only。

## 验证要求

- `uv run pytest -q tests/test_watchdog_memory_cursor_api.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_hub.py`
- `uv run python -m ai_sdlc verify constraints`

