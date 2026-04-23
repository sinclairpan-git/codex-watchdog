# Spec：072-memory-hub-preview-operator-readiness-docs

## 背景

`WI-071` 已把 `MemoryHubService.ai_autosdlc_cursor()` 接成真实 app-level preview route，并新增 app-level 开关 `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED`。但当前 repo-local operator 真值仍未收口：

- `config/examples/watchdog.env.example` 没有暴露该开关；
- `docs/getting-started.zh-CN.md` 没有说明 preview route 的启用方式、默认关闭语义和最小 smoke test；
- `src/watchdog/validation/docs_contracts.py` 与 `tests/test_long_running_autonomy_doc_contracts.py` 也没有锁住这部分文档契约。

这会让能力“代码可用，但 operator 无法从仓库真值里知道如何启用与验收”。

## 范围

### In Scope

- `config/examples/watchdog.env.example`
- `docs/getting-started.zh-CN.md`
- `src/watchdog/validation/docs_contracts.py`
- `tests/test_long_running_autonomy_doc_contracts.py`
- `ai_sdlc` 工单文档与状态同步

### Out of Scope

- 不在本工单内改动 `Memory Hub` runtime 语义；
- 不在本工单内新增新的 preview contract 或 route；
- 不在本工单内改动 Brain/provider/release gate 主链；
- 不在本工单内接入真实密钥、真实外部控制面或生产部署。

## Formal Source

- `specs/071-memory-hub-ai-autosdlc-preview-api/spec.md`
- `.ai-sdlc/work-items/071-memory-hub-ai-autosdlc-preview-api/latest-summary.md`
- `src/watchdog/settings.py`
- `src/watchdog/api/memory_hub_preview.py`
- `docs/getting-started.zh-CN.md`
- `config/examples/watchdog.env.example`

## 非 Owner 约束

- **FR-7201**：072 只补 operator-readiness / docs-contract 真值，不重新打开 `WI-071` 的 runtime owner。
- **FR-7202**：preview contract 仍须 default-off；文档只能把启用方式和默认关闭语义说明清楚，不得改默认值。
- **FR-7203**：该 route 仍属于 preview / operator 调试面，文档不得把它写成稳定主链 API。

## 功能需求

- **FR-7204**：`config/examples/watchdog.env.example` 必须显式暴露 `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=false`。
- **FR-7205**：`docs/getting-started.zh-CN.md` 必须说明如何把 `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED` 切到 `true`，并明确 route 为 `POST /api/v1/watchdog/memory/preview/ai-autosdlc-cursor`。
- **FR-7206**：`docs/getting-started.zh-CN.md` 必须明确 preview contract 默认保持 `enabled=false`，启用后才返回真实 stage-aware cursor。
- **FR-7207**：repo-local 文档契约校验必须锁住上述 env sample 与 getting-started 真值，防止后续回退。

## 验证要求

- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
