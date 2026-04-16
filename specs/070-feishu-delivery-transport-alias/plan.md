# Plan：070-feishu-delivery-transport-alias

## 目标

把 `WATCHDOG_DELIVERY_TRANSPORT=feishu` 从“文档真值”补成“runtime 可启动的正式输入”，同时保持 `feishu-app` 兼容。

## 实施边界

1. 先写失败测试，锁住 `delivery_transport="feishu"` 必须能构建 `FeishuAppDeliveryClient`。
2. 再做最小 runtime alias 修复，只扩 transport accept surface，不改 delivery client 语义。
3. 最后同步 `ai_sdlc` 状态并完成双专家复核。

## 验证

- `uv run pytest -q tests/test_watchdog_feishu_delivery.py tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`

