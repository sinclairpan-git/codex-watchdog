# Task Execution Log：070-feishu-delivery-transport-alias

- 2026-04-16：从 `WI-069` closeout 后继续巡检时，发现文档真值要求 `WATCHDOG_DELIVERY_TRANSPORT=feishu`，但 runtime 仅接受 `feishu-app`。
- 2026-04-16：新增红测 `test_create_app_accepts_documented_feishu_transport_alias`，确认当前 `create_app()` 会抛出 `unsupported delivery_transport: feishu`。
- 2026-04-16：在 `src/watchdog/main.py` 把 `feishu` 收敛为 `FeishuAppDeliveryClient` 的兼容 alias，并保留 `feishu-app` 兼容输入。
- 2026-04-16：重新运行 targeted tests、`ai_sdlc verify constraints`，并吸收 Hilbert / Gauss 对抗复核意见后关闭工单。

