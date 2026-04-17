# 外部集成 Smoke Harness 设计

## 背景

当前仓库已经完成以下外部能力面的 formal 落地：

- Feishu official ingress / direct delivery；
- OpenAI-compatible Brain provider runtime；
- Memory Hub `ai-autosdlc-cursor` preview route。

这些能力已经各自具备代码、文档与定向测试，但 operator 侧的最小验收仍分散在
`docs/getting-started.zh-CN.md` 的手工步骤与 `curl` 片段里。当前缺的不是新的 runtime
语义，而是一个 repo-local、可执行、可回归的统一 smoke harness，用来把三条能力面的
“是否已正确接线”收敛成单一入口。

本设计因此把下一步限定为一个 maintenance patch：把现有手工验收步骤脚本化，不新建
formal WI，不扩主链路 product semantics。

## 目标

新增一个统一的 smoke harness，让操作者或 CI 可以在本地快速回答以下问题：

1. Watchdog 当前实例是否可达；
2. Feishu official ingress 的最小 callback contract 是否可用；
3. OpenAI-compatible provider 配置是否完整，且 provider wiring 仍指向既有 runtime；
4. Memory Hub preview route 是否启用、是否返回符合 preview contract 的响应；
5. 失败时能否快速定位是环境缺失、入口不可达，还是 contract 漂移。
6. 在 operator 明确提供 project binding 时，Feishu official ingress 是否还能把 `/goal ...`
   文本事件归一到 `goal_contract_bootstrap`。

## 非目标

- 不引入新的 API route、settings 字段或 delivery / provider 行为；
- 不接入真实 Feishu 组织配置、真实 OpenAI token、真实外网依赖；
- 不把 smoke harness 变成 release orchestrator 或生产巡检系统；
- 不替代已有单元测试与 docs contract tests。

## 方案比较

### 方案 A：继续沿用手工 runbook

优点：零实现成本。  
缺点：证据不可回归、执行顺序靠人工、失败定位不稳定。

### 方案 B：新增统一 smoke harness

优点：把已有手工步骤收敛成单一命令，可在本地和 CI 重复执行，且不要求真实外部依赖。  
缺点：需要设计参数边界，避免脚本演变成第二套 runtime。

### 方案 C：直接做真实外部 E2E

优点：最接近真实接入。  
缺点：强依赖 secrets、外部平台、组织级配置，无法作为 repo-local 默认闭环。

## 结论

采用方案 B。

执行面只做一层受控的“本仓外部集成 smoke harness”，把当前文档中的手工验收顺序变成
统一脚本与测试。所有检查都必须保持 fail-closed，并且只验证已存在的正式能力面。

## 设计

### 1. 入口与目录

新增以下产物：

- `scripts/watchdog_external_integration_smoke.py`
- `tests/test_watchdog_external_integration_smoke.py`
- `docs/getting-started.zh-CN.md` 中新增统一 smoke harness 入口说明
- `README.md` 中同步指向正式 smoke 入口与当前 canonical 启动命令

脚本入口采用：

```bash
uv run python scripts/watchdog_external_integration_smoke.py
```

该脚本是单一 operator 入口；文档中的分项 `curl` 保留为定位参考，但不再是推荐主路径。

### 2. 参数与执行模式

脚本从环境读取既有变量，不新增新的设置字段。核心输入分为两类：

- 必选基础输入：
  - `WATCHDOG_BASE_URL`
  - `WATCHDOG_API_TOKEN`
- 按能力面启用的可选输入：
  - Feishu：`WATCHDOG_FEISHU_VERIFICATION_TOKEN`
- Feishu callback smoke：`WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID`、`WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`、`WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`、`WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S`
  - OpenAI-compatible：`WATCHDOG_BRAIN_PROVIDER_NAME`、`WATCHDOG_BRAIN_PROVIDER_BASE_URL`、`WATCHDOG_BRAIN_PROVIDER_API_KEY`、`WATCHDOG_BRAIN_PROVIDER_MODEL`
  - Memory Hub preview：`WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED`

脚本支持按目标收敛检查，默认执行 `all`，并允许仅执行单项：

- `all`
- `health`
- `feishu`
- `feishu-control`
- `provider`
- `memory`

目标选择用命令行参数；仅 `feishu-control` 这一可选 callback smoke 会额外读取 project binding
相关环境变量，其余 target 继续只依赖既有运行时变量。

### 3. 检查模型

每个检查项输出统一结果结构：

- `check_name`
- `status`：`passed` / `failed` / `skipped`
- `reason`
- `evidence`

统一结构的目的，是让脚本既可读，又能被后续测试或 CI 稳定断言。

脚本退出码规则如下：

- `0`：所有被请求的检查都通过；
- `1`：至少一个被请求的检查失败；
- `2`：命令参数错误或必选基础输入缺失。

`skipped` 只允许出现在“该检查未被请求”或“明确未启用该能力面”的情形；若用户请求了某项
检查，但对应必需环境缺失，则必须判定为 `failed`，不能静默跳过。

### 4. 数据流

#### 4.1 Health

对 `GET /healthz` 发起请求，验证 Watchdog 服务可达。失败则直接标记 `health` 为 `failed`，
并阻断后续需要服务可达的远程检查。

#### 4.2 Feishu ingress smoke

在本地构造文档已定义的 `url_verification` 请求体，调用：

- `POST /api/v1/watchdog/feishu/events`

断言返回 `200` 且响应体包含原始 `challenge`。该检查只验证 Watchdog 侧 callback contract，
不尝试模拟完整 Feishu 平台签名或真实消息流。

#### 4.2.1 Feishu callback goal bootstrap smoke

当 operator 显式提供：

- `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S`

时，脚本允许额外执行 `feishu-control` target。该 target 仍然只调用既有入口；若仓内历史数据较大导致 DM synthetic smoke 超过默认公共 HTTP 窗口，只放宽 `WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S`，不修改其余 remote target 的 timeout：

- `POST /api/v1/watchdog/feishu/events`

但请求体改为构造一条最小的 `im.message.receive_v1` 文本事件，消息内容固定为：

- `repo:<project_id> /goal <goal_message>`

断言响应满足：

- `accepted == true`
- `event_type == "goal_contract_bootstrap"`
- `data.project_id` 与输入绑定一致
- `data.session_id` 非空；若显式提供 `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`，则必须匹配
- `data.goal_contract_version` 非空

该 target 的目的，是补一条 repo-local、可回归的 callback contract smoke，验证 official ingress
仍能把文本 DM 事件归一为正式 control request；它不是组织级真实 E2E，也不要求真实 Feishu
后台投递消息。

#### 4.3 Provider wiring smoke

该项不依赖真实外网调用，但不能只停留在“环境变量齐全性检查”。它必须分成两层：

1. **模式检查**：确认当前环境是否显式切到 `openai-compatible`；
2. **本地 wiring probe**：复用现有 `BrainDecisionService` / provider runtime 选择逻辑，
   对一份固定 synthetic record 做一次进程内 probe。

当 provider 模式被显式开启时，probe 必须在 stub transport 下证明两件事：

- 正常响应时，返回的 `DecisionIntent.provider == "openai-compatible"`；
- provider 超时或失败时，返回的 fallback provider 仍是 `resident_orchestrator`。

这样验证的是“当前代码与环境组合下，brain runtime 仍会选中既有 provider 语义”，而不是只
验证 `.env` 文案是否看起来完整。

若 `WATCHDOG_BRAIN_PROVIDER_NAME != openai-compatible`，则：

- 当目标是 `provider` 或 `all` 时，返回 `skipped`，并明确说明当前实例未启用外部 provider；
- 不把默认 resident 模式误判为失败。

若已显式切到 `openai-compatible`，但 `base_url/api_key/model` 任一缺失，则返回 `failed`；
若配置完整但 local wiring probe 未通过，也必须返回 `failed`。

#### 4.4 Memory Hub preview smoke

对以下入口发起带 Bearer token 的请求：

- `POST /api/v1/watchdog/memory/preview/ai-autosdlc-cursor`

使用一份固定、最小、与现有测试对齐的 preview request body。断言：

- HTTP `200`
- `success == true`
- `data.contract_name == "ai-autosdlc-cursor"`

若环境声明预览开关开启，则额外要求 `data.enabled == true`；若未开启，则要求
`data.enabled == false`。这样脚本验证的是“开关与 route 语义一致”，而不是把 preview
默认关闭误判成异常。

### 5. 实现边界

为了避免脚本变成第二套 runtime，脚本只承担：

- 参数解析；
- 发请求；
- 汇总结果；
- 生成人类可读输出。

脚本不承担：

- secret 管理；
- 外部 provider 真实 completion 调用；
- Feishu 真实消息投递；
- 任何状态修复或自动回写。

### 6. 失败策略

失败输出必须直接指出原因类别，至少覆盖：

- `service_unreachable`
- `missing_required_env`
- `unexpected_http_status`
- `contract_mismatch`
- `feature_not_enabled`

所有失败都必须带最小证据，例如目标 URL、缺失字段名、关键响应字段摘要。输出需要对
token 做脱敏，避免把完整 secret 打到终端。

### 7. 测试设计

测试采用 TDD，至少覆盖：

1. 参数解析与目标选择；
2. 基础环境缺失时的退出码与错误消息；
3. `health` 成功/失败路径；
4. Feishu URL verification contract 成功/失败路径；
5. provider 处于 resident 默认模式时的 `skipped` 语义；
6. provider 显式启用但配置缺失时的失败语义；
7. Memory Hub preview 在 disabled/enabled 两种模式下的断言；
8. 汇总输出与退出码映射。
9. `all` 与可选 `feishu-control` target 的组合语义。

测试应优先使用可注入的 HTTP client 或 transport stub，避免依赖真实网络与真实服务进程。

### 8. 文档同步

`docs/getting-started.zh-CN.md` 需要新增一段正式入口说明，明确：

- 推荐的统一 smoke 命令；
- 各目标检查分别验证什么；
- 哪些情况会返回 `skipped`；
- 原有 `curl` 片段仍作为手工排障参考。

`README.md` 也必须同步到同一 truth surface，避免 operator 在仓库首页看到与 getting-started
不同的启动或 smoke 入口。

`docs_contracts` 与对应测试应锁住以下真值：

- 统一 smoke 脚本路径；
- `docs/getting-started.zh-CN.md` 中的推荐命令；
- `README.md` 中的 canonical 启动命令与 smoke 入口。

## 验证

实现阶段至少需要以下验证：

- `uv run pytest -q tests/test_watchdog_external_integration_smoke.py`
- 相关 docs contract tests
- `uv run python -m ai_sdlc verify constraints`

若脚本入口最终落在文档正式推荐路径中，则验证必须覆盖“脚本存在且文档指向正确入口”。
