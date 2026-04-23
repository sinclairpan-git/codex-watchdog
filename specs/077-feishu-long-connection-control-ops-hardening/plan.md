# Plan：077-feishu-long-connection-control-ops-hardening

## 目标

把当前已实现但未正式建档的 Feishu 长连接控制桥接、repo-local live acceptance 配套，以及为其补上的 approval / delivery / session / ops 可靠性增强，重新收口为一个独立的 `WI-077`。

## 实施边界

1. 先确认 `WI-076` 已完成，当前 dirty WIP 的真实边界是新的 long connection/control/ops hardening，而不是旧工单尾巴。
2. 冻结 `long_connection` 的正式范围：显式 sidecar、复用既有 ingress/control 路径、HTTP callback 保留 fallback。
3. 吸收当前已经存在的 secrets、smoke config、ingress normalization、store hardening 与 ops requeue/health summary 实现，避免口径漂移。
4. 同步 `README`、getting-started、live acceptance、env example 与 docs contract，使文档真值与代码一致。
5. 通过 targeted verification、`ruff` 与 `ai_sdlc verify constraints` 完成 `WI-077` closeout。

## 验证

- `uv run pytest -q tests/test_watchdog_feishu_long_connection.py`
- `uv run pytest -q tests/test_watchdog_external_integration_smoke.py -k 'long_connection or feishu'`
- `uv run pytest -q tests/test_watchdog_main.py tests/test_watchdog_secrets.py`
- `uv run pytest -q tests/test_watchdog_feishu_ingress.py tests/test_watchdog_feishu_delivery.py tests/test_watchdog_delivery_worker.py`
- `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_approval_loop.py tests/test_watchdog_session_spine_store_atomicity.py`
- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py tests/test_watchdog_action_receipts.py tests/test_watchdog_delivery_store.py`
- `uv run ruff check src/watchdog/api/feishu_ingress.py src/watchdog/api/ops.py src/watchdog/main.py src/watchdog/secrets.py src/watchdog/services/approvals/service.py src/watchdog/services/feishu_ingress/service.py src/watchdog/services/feishu_long_connection/service.py src/watchdog/validation/external_integration_smoke.py scripts/watchdog_external_integration_smoke.py scripts/watchdog_feishu_long_connection.py tests/test_watchdog_feishu_long_connection.py tests/test_watchdog_main.py tests/test_watchdog_secrets.py tests/test_watchdog_session_spine_store_atomicity.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
