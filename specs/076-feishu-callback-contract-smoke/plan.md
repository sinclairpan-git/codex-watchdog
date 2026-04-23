# Plan：076-feishu-callback-contract-smoke

## 目标

在不突破 repo-local 边界的前提下，为 external integration smoke harness 增补一条可回归的 Feishu callback contract smoke，并完成由该交付触发的全量回归修复与正式 `ai_sdlc` 收口。

## 实施边界

1. 先冻结 `feishu-control` 的边界：可选 target、official ingress、repo-local callback contract，不重开真实外部 E2E。
2. 再在 `external_integration_smoke` 与 CLI 入口里实现最小 callback smoke，并补对应测试。
3. 同步 operator 文档、env example、docs contract 与架构设计，使仓库真值一致。
4. 修复全量回归里暴露出的 `feishu/responses` compatibility receipt 幂等冲突。
5. 以双对抗评审、全量测试和 `ai_sdlc verify` 完成本工单收口。

## 验证

- `uv run pytest -q tests/test_watchdog_external_integration_smoke.py tests/test_long_running_autonomy_doc_contracts.py tests/test_watchdog_feishu_ingress.py`
- `uv run pytest -q tests/test_watchdog_approval_loop.py::test_feishu_response_api_uses_response_tuple_as_idempotency_key`
- `uv run pytest -q`
- `uv run ruff check src/watchdog/api/feishu_responses.py src/watchdog/validation/external_integration_smoke.py scripts/watchdog_external_integration_smoke.py tests/test_watchdog_external_integration_smoke.py src/watchdog/validation/docs_contracts.py tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
