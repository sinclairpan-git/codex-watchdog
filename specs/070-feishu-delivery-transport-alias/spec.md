# Spec：070-feishu-delivery-transport-alias

## 背景

`WI-069` 已把 Feishu 接入真值固定为：

- `config/examples/watchdog.env.example` 使用 `WATCHDOG_DELIVERY_TRANSPORT=feishu`
- `docs/getting-started.zh-CN.md` 也要求切到 `WATCHDOG_DELIVERY_TRANSPORT=feishu`
- `src/watchdog/validation/docs_contracts.py` 已把这条文档真值锁成 repo-local contract

但 runtime 仍存在一处未对齐：

- `src/watchdog/main.py` 的 `_build_delivery_client()` 只接受 `feishu-app` 或 `openclaw`

这会导致用户按仓库内正式文档配置 `WATCHDOG_DELIVERY_TRANSPORT=feishu` 时，`create_app()` 在启动阶段直接抛出 `ValueError("unsupported delivery_transport: feishu")`，使 `WI-069` 刚关闭的接入路径不可运行。

## 范围

### In Scope

- `src/watchdog/main.py`
- `tests/test_watchdog_feishu_delivery.py`
- `ai_sdlc` 工单文档与状态同步

### Out of Scope

- 不在本工单内新增新的 Feishu delivery runtime 语义；
- 不在本工单内重写 `WI-069` 的文档真值；
- 不在本工单内引入真实 staging/production secrets。

## Formal Source

- `docs/getting-started.zh-CN.md`
- `config/examples/watchdog.env.example`
- `src/watchdog/validation/docs_contracts.py`
- `specs/069-feishu-openai-integration-readiness/spec.md`
- `specs/064-feishu-direct-delivery-runtime/spec.md`

## 非 Owner 约束

- **FR-7001**：070 只修 transport alias / runtime accept-surface 与文档真值的对齐，不改 Feishu 直投实现本身。
- **FR-7002**：`WATCHDOG_DELIVERY_TRANSPORT=feishu` 必须成为 runtime 可接受的正式输入；已有 `feishu-app` 兼容输入不得被静默打断。
- **FR-7003**：除非显式重开文档 owner，否则不得回滚 `WI-069` 已冻结的 `feishu` 文档真值。

## 功能需求

- **FR-7004**：`create_app()` 在 `Settings(delivery_transport="feishu")` 时必须构建 `FeishuAppDeliveryClient`，不得再抛 unsupported transport。
- **FR-7005**：`create_app()` 在 `Settings(delivery_transport="feishu-app")` 时必须继续保持兼容。
- **FR-7006**：repo-local 测试必须显式覆盖 `feishu` alias 回归，防止后续再次漂移。

## 验证要求

- `uv run pytest -q tests/test_watchdog_feishu_delivery.py tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`

