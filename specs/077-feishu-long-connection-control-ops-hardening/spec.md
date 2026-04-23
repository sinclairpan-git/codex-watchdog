# Spec：077-feishu-long-connection-control-ops-hardening

## 背景

`WI-076` 已正式收口 repo-local Feishu callback contract smoke，但当前工作区残留的中断 WIP 已明显超出该工单边界：

- 仓库已引入 Feishu `long_connection` 事件/回调模式与独立运行脚本；
- `feishu ingress -> control` 归一化已向默认 project binding、session spine store、DM 审批回复识别继续扩展；
- external integration smoke、getting-started、live acceptance 文档与 env sample 已切到“长连接优先，HTTP callback 保留 fallback”的操作口径；
- 为支撑这条控制链路的 live acceptance，approval / delivery / session / ops surfaces 也追加了原子写入、重试恢复、健康摘要与 transport failure requeue 等可靠性补强。

因此当前真实任务不是继续修改 `076`，而是把这批已存在的 Feishu 长连接控制桥接与 ops hardening 改动，按 `ai_sdlc` 框架重新 formalize 为新的 `WI-077` 并完成 closeout。

## 范围

### In Scope

- 为 Feishu event / callback transport 增补 `long_connection` 模式与 repo-local sidecar runtime
- 保持 `/api/v1/watchdog/feishu/events` HTTP callback 路径可用，并把其降级为 fallback / contract surface
- 扩展 Feishu ingress normalization，使 DM 文本在默认 project binding、session spine store 与审批回复语义下可继续归一
- 为 long connection / live acceptance 补齐必要的 smoke config、secrets 解析、operator docs 与 docs contract
- 为该控制链路补齐 approval / delivery / session / ops 的原子写入、去重、requeue 与健康摘要能力
- 将以上已完成实现按 `WI-077` 正式回写到 `specs/` 与 `.ai-sdlc/work-items/`

### Out of Scope

- 不在本工单内证明真实 Feishu 组织安装、外网回调打通或生产级验收
- 不把 long connection runtime 自动挂进主应用生命周期
- 不删除或替换既有 HTTP callback fallback
- 不把卡片动作回调扩展成新的完整审批产品语义或新的状态机

## Formal Source

- `src/watchdog/services/feishu_long_connection/service.py`
- `scripts/watchdog_feishu_long_connection.py`
- `src/watchdog/services/feishu_ingress/service.py`
- `src/watchdog/api/feishu_ingress.py`
- `src/watchdog/services/feishu_control/service.py`
- `src/watchdog/validation/external_integration_smoke.py`
- `scripts/watchdog_external_integration_smoke.py`
- `src/watchdog/secrets.py`
- `src/watchdog/api/ops.py`
- `src/watchdog/main.py`
- `src/watchdog/services/approvals/service.py`
- `src/watchdog/services/delivery/store.py`
- `src/watchdog/services/delivery/worker.py`
- `src/watchdog/services/session_service/store.py`
- `src/watchdog/services/session_spine/store.py`
- `README.md`
- `docs/getting-started.zh-CN.md`
- `docs/operations/external-integration-live-acceptance.md`
- `config/examples/watchdog.env.example`

## 非 Owner 约束

- **FR-7701**：Feishu 长连接能力必须保持为显式 sidecar/runtime 入口，不得在本工单内改成应用默认自启动。
- **FR-7702**：`long_connection` 只是在 transport 层替代 HTTP callback，不得改写 `feishu ingress -> control` 的既有归一路径。
- **FR-7703**：repo-local smoke 若处于 `long_connection` 模式，只能验证配置完备性与 SDK 依赖，不得虚构真实外网投递成功。
- **FR-7704**：本工单新增的可靠性补强必须服务于现有 approval / delivery / session / ops surfaces，不得借机引入新的控制面产品边界。

## 功能需求

- **FR-7705**：当 `WATCHDOG_FEISHU_EVENT_INGRESS_MODE` 或 `WATCHDOG_FEISHU_CALLBACK_INGRESS_MODE` 为 `long_connection` 时，仓库必须提供可独立启动的 Feishu 长连接 runtime，并显式要求 `app_id + app_secret + verification_token + lark-oapi`。
- **FR-7706**：Feishu 长连接 runtime 必须复用现有 `FeishuIngressNormalizationService` 与 `FeishuControlService`，而不是旁路出新的 control surface。
- **FR-7707**：Feishu ingress normalization 必须支持默认 project binding、session spine store 反查，以及 DM 审批/执行回复文本的最小归一。
- **FR-7708**：当消息来自 DM chat 且可解析为控制请求时，归一化结果必须保留 `chat_id` 作为 `receive_id(chat_id)`，用于后续回发。
- **FR-7709**：`external_integration_smoke` 与 CLI 入口必须支持长连接模式下的 repo-local 配置验证，并允许 `feishu-control` 使用更长的 HTTP timeout。
- **FR-7710**：brain provider API key 必须支持“显式 env 优先，macOS Keychain service/account fallback”解析策略。
- **FR-7711**：approval / delivery / session / spine 相关 JSON stores 必须提供原子写入、去重或恢复能力，以支撑长连接/live acceptance 下的重复事件与重试场景。
- **FR-7712**：ops surface 必须暴露最小 health summary，并提供对 transport failure envelopes 的手动 requeue 入口。
- **FR-7713**：README、getting-started、live acceptance、env example 与 docs contracts 必须同步“长连接优先、HTTP fallback 保留”的仓库真值。

## 验证要求

- `uv run pytest -q tests/test_watchdog_feishu_long_connection.py tests/test_watchdog_external_integration_smoke.py -k 'long_connection or feishu' tests/test_watchdog_main.py tests/test_watchdog_secrets.py`
- `uv run pytest -q tests/test_watchdog_feishu_ingress.py tests/test_watchdog_feishu_delivery.py tests/test_watchdog_delivery_worker.py`
- `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_approval_loop.py tests/test_watchdog_session_spine_store_atomicity.py`
- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py tests/test_watchdog_action_receipts.py tests/test_watchdog_delivery_store.py`
- `uv run ruff check src/watchdog/api/feishu_ingress.py src/watchdog/api/ops.py src/watchdog/main.py src/watchdog/secrets.py src/watchdog/services/approvals/service.py src/watchdog/services/feishu_ingress/service.py src/watchdog/services/feishu_long_connection/service.py src/watchdog/validation/external_integration_smoke.py scripts/watchdog_external_integration_smoke.py scripts/watchdog_feishu_long_connection.py tests/test_watchdog_feishu_long_connection.py tests/test_watchdog_main.py tests/test_watchdog_secrets.py tests/test_watchdog_session_spine_store_atomicity.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
