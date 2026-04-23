# Spec：069-feishu-openai-integration-readiness

## 背景

当前仓库已经具备以下 runtime 能力：

- `WI-062` 已完成 `OpenAI-compatible` Brain provider runtime；
- `WI-064` 已完成 Feishu outbound direct delivery；
- `WI-068` 已完成 Feishu 官方 ingress / event subscription contract。

但外部接入真值仍未正式闭环：

- `config/examples/watchdog.env.example` 还没有把 Feishu ingress/outbound 与 `OpenAI-compatible` provider 的启用变量作为正式样例暴露出来；
- `docs/getting-started.zh-CN.md` 仍主要覆盖 Feishu webhook / resident orchestrator 默认路径，没有给出 “如何切到 Feishu 主控制面 + OpenAI-compatible provider” 的正式接入与验收顺序。

`WI-069` 的目标是把这部分“可运行能力”和“可接入真值”对齐，但不再扩新的 runtime 行为。

## 范围

### In Scope

- `config/examples/watchdog.env.example`
- `docs/getting-started.zh-CN.md`
- `src/watchdog/validation/docs_contracts.py`
- `tests/test_long_running_autonomy_doc_contracts.py`
- `ai_sdlc` 工单文档与状态同步

### Out of Scope

- 不在本工单内创建或安装 Feishu 自建应用本身；
- 不在本工单内引入新的 Feishu runtime 语义；
- 不在本工单内改写 Brain provider runtime 行为；
- 不在本工单内接入真实外网密钥或生产 secrets。

## Formal Source

- `docs/getting-started.zh-CN.md`
- `config/examples/watchdog.env.example`
- `specs/062-global-design-provider-memory-closure/spec.md`
- `specs/064-feishu-direct-delivery-runtime/spec.md`
- `specs/068-feishu-ingress-event-subscription-contract/spec.md`

## 非 Owner 约束

- **FR-6901**：069 只补接入就绪/config sample/runbook 真值，不扩新的 runtime product semantics。
- **FR-6902**：runtime 默认值仍保持兼容；env sample 只能增加显式开关与样例，不得偷偷改变默认 transport / provider。
- **FR-6903**：Feishu app 创建、机器人安装、Feishu 宿主插件部署仍属于仓库外职责；本工单只提供本仓库侧的可照抄配置和启用顺序。

## 功能需求

- **FR-6904**：`config/examples/watchdog.env.example` 必须显式暴露 Feishu official ingress / direct delivery 所需的关键变量：
  - `WATCHDOG_DELIVERY_TRANSPORT`
  - `WATCHDOG_FEISHU_APP_ID`
  - `WATCHDOG_FEISHU_APP_SECRET`
  - `WATCHDOG_FEISHU_VERIFICATION_TOKEN`
  - `WATCHDOG_FEISHU_RECEIVE_ID`
  - `WATCHDOG_FEISHU_RECEIVE_ID_TYPE`
- **FR-6905**：`config/examples/watchdog.env.example` 必须显式暴露 `OpenAI-compatible` provider 所需的关键变量：
  - `WATCHDOG_BRAIN_PROVIDER_NAME`
  - `WATCHDOG_BRAIN_PROVIDER_BASE_URL`
  - `WATCHDOG_BRAIN_PROVIDER_API_KEY`
  - `WATCHDOG_BRAIN_PROVIDER_MODEL`
- **FR-6906**：`docs/getting-started.zh-CN.md` 必须提供 Feishu 模式启用说明，明确：
  - 何时把 `delivery_transport` 切到 `feishu`
  - 官方 ingress callback path 是 `/api/v1/watchdog/feishu/events`
  - 如何做 URL verification / event ingress 的最小验收
- **FR-6907**：`docs/getting-started.zh-CN.md` 必须提供 `OpenAI-compatible` provider 启用说明，明确：
  - `WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible`
  - `base_url + api_key + model` 的配置方式
  - provider 失败时仍会 fail-closed 回退到既有 rule-based/runtime path
- **FR-6908**：repo-local 文档契约测试必须锁住上述接入真值，防止后续文档/样例漂移。

## 验证要求

- `tests/test_long_running_autonomy_doc_contracts.py` 必须覆盖 Feishu / OpenAI-compatible integration readiness checks；
- `config/examples/watchdog.env.example` 与 `docs/getting-started.zh-CN.md` 的相关片段必须通过 validator；
- `ai_sdlc verify constraints` 通过。
