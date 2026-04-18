# External Integration Live Acceptance

这份 runbook 只定义真实环境联调与验收步骤，用来确认仓库内已经实现的外部契约能在 staging / production-like 环境被正确接线。

边界固定如下：

- 它不是新的 product work item，也不替代 `.ai-sdlc/` 的正式 backlog。
- 它不声明外部组织安装、域名、证书、密钥轮换、凭证发放已经自动完成。
- 它不替代 `docs/operations/release-gate-runbook.md`；release gate 与 live acceptance 必须同时成立，才能对外声称“当前接线就绪”。
- 它不是 production acceptance gate；外部平台最终放量、组织级权限开通、正式公网入口与密钥轮换仍属于仓库外运维真值。

## Preconditions

执行这份 runbook 前，至少确认：

1. Watchdog 已部署，并且 `GET /healthz` 可达。
2. 真实环境的 `WATCHDOG_API_TOKEN` 已配置完成，且可用于受保护接口。
3. 若要验收 Feishu 官方入口，外部自建应用、verification token 已在平台侧配置；若本地无公网域名，则事件配置与回调配置应切到长连接模式。
4. 若要验收 OpenAI-compatible provider，`base_url`、`api_key`、`model` 已在真实环境中完成注入。
5. 若要验收 Memory Hub preview，调用方已明确接受它仍是 preview contract，而非 runtime source of truth。

## Required Configuration Surface

最小环境变量面如下；允许通过密钥管理或部署平台注入，但验收时必须确认这些值确实存在于运行环境：

### Watchdog base

- `WATCHDOG_BASE_URL`
- `WATCHDOG_API_TOKEN`

### Feishu official ingress and direct delivery

- `WATCHDOG_FEISHU_EVENT_INGRESS_MODE=long_connection|callback`
- `WATCHDOG_FEISHU_CALLBACK_INGRESS_MODE=long_connection|callback`
- `WATCHDOG_DELIVERY_TRANSPORT=feishu`
- `WATCHDOG_FEISHU_APP_ID`
- `WATCHDOG_FEISHU_APP_SECRET`
- `WATCHDOG_FEISHU_VERIFICATION_TOKEN`
- `WATCHDOG_FEISHU_RECEIVE_ID`
- `WATCHDOG_FEISHU_RECEIVE_ID_TYPE`

### OpenAI-compatible Brain provider

- `WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible`
- `WATCHDOG_BRAIN_PROVIDER_BASE_URL`
- `WATCHDOG_BRAIN_PROVIDER_API_KEY`
- `WATCHDOG_BRAIN_PROVIDER_MODEL`

### Optional provider live acceptance tuning

- `WATCHDOG_SMOKE_PROVIDER_LIVE=true|false`
- `WATCHDOG_SMOKE_PROVIDER_HTTP_TIMEOUT_S`

### Memory Hub preview toggle

- `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=true|false`

### Optional Feishu callback contract smoke inputs

- `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S`（可选；真实数据量较大时可单独放宽 DM synthetic smoke 的超时窗口，默认 15 秒）
- `WATCHDOG_SMOKE_FEISHU_DISCOVERY_COMMAND_TEXT`（可选；默认 `项目列表`）
- `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS`（逗号分隔；用于多项目目录发现验收）
- `WATCHDOG_SMOKE_FEISHU_DISCOVERY_HTTP_TIMEOUT_S`（可选；真实数据量较大时可单独放宽多项目目录 smoke 的超时窗口，默认 30 秒）

其中 `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID` 与 `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE` 必须由操作者显式确认是本次可写验收要命中的 live target。不要从 discovery 返回的候选项目列表、样例 env、测试数据或仓库同名项目里自动猜填；`feishu-control` synthetic smoke 会进入真实 `goal_contract_bootstrap` 写路径，并可能连带 supersede pending approvals / delivery outbox。若该 target 因 live target 缺失返回 `skipped`，evidence 必须显式包含 `required_action=confirm_mutating_live_target`，且整包验收继续按 fail-closed 记为未完成。

## Acceptance Flow

按下面顺序执行，避免把外部平台接线问题和仓库内 contract drift 混在一起。

### 1. Health and auth

先确认基础存活和鉴权：

```bash
curl -H "Authorization: Bearer <WATCHDOG_API_TOKEN>" \
  "${WATCHDOG_BASE_URL}/healthz"

uv run python scripts/watchdog_external_integration_smoke.py --target health
```

通过标准：

- `GET /healthz` 返回成功；
- smoke `health` 返回 `passed`；
- 若这里失败，后续 Feishu / provider / memory 验收一律不成立。

### 2. Feishu long-connection ingress / callback verification

若真实环境没有公网域名，先把 Watchdog 主服务启动好，再单独启动 Feishu 长连接 bridge：

```bash
set -a
source .env.w
set +a
uv run python scripts/watchdog_feishu_long_connection.py
```

然后在飞书控制台完成：

1. “事件配置”选择“使用长连接接收事件”；
2. 在“事件配置”里添加 `im.message.receive_v1`（接收消息 v2.0）；
3. 同时添加 `im.chat.access_event.bot_p2p_chat_entered_v1`（控制台文案通常对应机器人进入单聊），用于首聊建链与捕获 `chat_id`；
4. “回调配置”也选择长连接模式；
5. 点击“验证”，确认 bridge 在线；
6. 确认机器人相关权限、应用可用范围与当前测试用户已发布生效；如果这里只保存了长连接，但事件或权限未发布，平台不会投递 DM。

随后执行仓库内的 Feishu smoke：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target feishu
```

这一步在长连接模式下会验证：

- 必需凭证存在；
- `lark-oapi` 已安装；
- 仓库内长连接 bridge 所需配置闭环成立。

HTTP callback fallback 仍然保留。必要时可手工复验 repo-local 的 `url_verification` 契约：

```bash
curl -X POST "${WATCHDOG_BASE_URL}/api/v1/watchdog/feishu/events" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "url_verification",
    "token": "<WATCHDOG_FEISHU_VERIFICATION_TOKEN>",
    "challenge": "challenge-123"
  }'
```

通过标准：

- 长连接 bridge 成功连上后，飞书控制台“验证”通过；
- smoke 返回 `passed`；
- HTTP fallback 的 `url_verification` 仍能回显 `challenge`；
- 若用户私聊机器人后，本地没有 `feishu long-connection message received: chat_id=...`，应先到飞书后台“日志检索 > 事件日志检索”核对 `im.message.receive_v1` 是否被平台实际推送；
- 若飞书平台侧仍未安装或长连接未生效，应标记为外部平台 blocker，而不是仓库功能缺失。

### 3. Feishu control-plane DM contract

若真实环境要让控制面通过 Feishu DM 触发目标收敛，继续执行：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-control
```

这一项会向 `POST /api/v1/watchdog/feishu/events` 发送 `im.message.receive_v1` 文本事件，消息体固定为：

```text
repo:<project_id> /goal <goal_message>
```

它不是只读探活。只要请求被真实环境接受，就可能创建或修订 goal contract，并对当前 project/session 的待批记录产生 supersede 副作用。

通过标准：

- 结果不是 `skipped` 时，必须落成 `goal_contract_bootstrap`；
- 若设置了 `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`，返回 session id 必须一致；
- 若 callback contract 在真实数据量下超过默认公共 HTTP 窗口，可仅调整 `WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S`，不要顺手放大全局 `WATCHDOG_HTTP_TIMEOUT_S`；
- 如果变量未配置而出现 `skipped`，这只能说明真实 DM smoke 尚未执行，不能当作控制面已验收完成；
- 若只有候选 `project_id` 列表、但没有经操作者确认的 `project_id + goal_message` 组合，必须保持 fail-closed，不得自动补值后继续跑 live smoke；
- 若真实用户在 Feishu 中直接发送同格式 DM，也应触发相同 contract，而不是另一套私有入口；
- 无公网域名场景下，这条 DM 应通过长连接 bridge 进入系统，而不是要求外部回调地址可达。
- 如果 synthetic smoke 通过、但真实 DM 仍无日志，归因应收敛为飞书控制台事件订阅/权限/发布状态，而不是仓库内 control contract 缺失。

### 3.1 Feishu multi-project discovery contract

若真实环境要验证多项目目录在 Feishu 中可见，单独执行：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-discovery
```

这一项会向 `POST /api/v1/watchdog/feishu/events` 发送 `im.message.receive_v1` 文本事件，默认消息体为：

```text
项目列表
```

通过标准：

- 结果不是 `skipped` 时，必须落成 `command_request`，且 `data.intent_code=list_sessions`、`data.reply_code=session_directory`；
- 返回的 `sessions[].project_id` 必须覆盖 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS` 中声明的项目集合；
- 若真实数据量下超过默认公共 HTTP 窗口，可仅调整 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_HTTP_TIMEOUT_S`，不要顺手放大全局 `WATCHDOG_HTTP_TIMEOUT_S`；
- 如果变量未配置而出现 `skipped`，这只能说明多项目目录 smoke 尚未执行，不能当作 Feishu 项目发现链路已验收完成；
- 若 synthetic smoke 通过、但真实 Feishu 仍只看到单项目，归因应继续收敛到投递目标、receive id 绑定或飞书侧会话可见性，而不是 session directory contract 缺失。

### 4. OpenAI-compatible provider wiring

切换到通用的 OpenAI-compatible provider 后执行：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target provider
```

默认的 `provider` smoke 仍保留 synthetic contract，用于仓库内回归。要做真实外部联调时，显式开启：

```bash
WATCHDOG_SMOKE_PROVIDER_LIVE=true \
uv run python scripts/watchdog_external_integration_smoke.py --target provider
```

若上游 provider 响应时间明显长于基础健康检查，可额外设置 `WATCHDOG_SMOKE_PROVIDER_HTTP_TIMEOUT_S`，只放宽这一项的验收窗口。

通过标准：

- `WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible` 已生效；
- provider smoke 返回 `passed`；
- 开启 `WATCHDOG_SMOKE_PROVIDER_LIVE=true` 时，success probe 必须真实命中当前配置的 `base_url`，而不是只跑 repo-local mock；
- provider 配置缺失、认证失败或上游报错时，系统保持 fail-closed 或降级，不得 silent pass；
- 只有在 `WATCHDOG_BRAIN_PROVIDER_BASE_URL`、`WATCHDOG_BRAIN_PROVIDER_API_KEY`、`WATCHDOG_BRAIN_PROVIDER_MODEL` 都完整时，才可声称 provider 接线就绪。

### 5. Memory Hub preview contract

若需要对外暴露 stage-aware preview cursor，执行：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target memory
```

必要时手工调用：

```bash
curl -X POST "${WATCHDOG_BASE_URL}/api/v1/watchdog/memory/preview/ai-autosdlc-cursor" \
  -H "Authorization: Bearer <WATCHDOG_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "request": {
      "project_id": "demo-project",
      "goal": "Close remaining operator readiness gaps",
      "current_stage": "execute",
      "recent_actions": ["run live acceptance"],
      "latest_summary": "external integration runbook verification"
    },
    "quality": {
      "context_compression_ratio": 0.42,
      "summary_freshness_seconds": 90,
      "artifact_recall_ratio": 0.88,
      "pending_questions": []
    }
  }'
```

通过标准：

- route 固定为 `POST /api/v1/watchdog/memory/preview/ai-autosdlc-cursor`；
- 响应包含 `contract_name=ai-autosdlc-cursor`；
- 开关为 `true` 时返回 `enabled=true`；
- 开关为 `false` 时 route 仍可调用，但语义必须保持 `enabled=false`；
- 这条 preview contract 不能被描述成 Memory Hub 已接管主链决策真值。

### 6. Full live acceptance smoke bundle

完成单项检查后，再跑一次完整收束：

```bash
uv run python scripts/watchdog_external_integration_smoke.py
uv run python scripts/watchdog_external_integration_smoke.py --target feishu
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-control
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-discovery
uv run python scripts/watchdog_external_integration_smoke.py --target provider
uv run python scripts/watchdog_external_integration_smoke.py --target memory
uv run python scripts/watchdog_external_integration_smoke.py \
  --target feishu-control \
  --target feishu-discovery \
  --target provider \
  --target memory \
  --markdown-report artifacts/watchdog-live-acceptance.md
```

通过标准：

- 默认 smoke 至少覆盖 `health`、`feishu`、`provider`、`memory`；
- `feishu-control` 在真实环境若需要控制面 DM，则应单独跑到 `passed`；
- `feishu-discovery` 在真实环境若需要多项目目录可见性，则应单独跑到 `passed`；
- resident expert 相关证据必须可复现：canonical replay 中要能 materialize `resident_expert_consultation`，session directory 要暴露 `resident_expert_coverage`，stale expert 时 ops / health 语义必须同步降级；
- 任何已启用能力只要返回字段缺失、contract mismatch 或回退语义异常，都应判为阻断，不得口头放行。

## Evidence Bundle

每次真实环境验收至少沉淀以下证据：

1. 执行时间、环境名、部署提交 SHA。
2. `GET /healthz` 返回摘要。
3. smoke 输出摘要，允许脱敏，但不能只写“通过”。
4. 若使用 `--markdown-report`，保留生成出的 Markdown 验收记录。
5. Feishu 回调 URL 与 receive id 的脱敏记录。
6. provider 的 `base_url`、`model` 与鉴权方式说明，token 必须脱敏。
7. 若执行了 `feishu-control`，记录 `project_id`、`goal_message`、返回 session id。
8. 若执行了 `feishu-discovery`，记录 `command_text`、期望项目集合与实际返回项目集合。
9. 若执行了 Memory preview，记录 `enabled=true|false` 与 `contract_name=ai-autosdlc-cursor`。
10. resident expert replay 证据：至少保留一次能 materialize `resident_expert_consultation` 的 replay 结果，并记录 `consultation_ref`、`coverage_status` 与专家状态摘要。
11. session directory 证据：保留 `resident_expert_coverage` 摘要，至少包含 `coverage_status`、`available_expert_count`、`stale_expert_count`、`latest_consultation_ref`。
12. 若存在 stale expert，保留 `healthz` / ops degraded 证据，证明 session directory 的 degraded 状态与健康面降级同向，而不是读面分叉。

## Fail-Closed Rules

建议统一使用以下失败分类，避免 operator 在记录结果时把平台问题与 contract drift 混写：

- `service_unreachable`
- `missing_required_env`
- `unexpected_http_status`
- `contract_mismatch`
- `feature_not_enabled`

以下情况一律不得对外宣称“服务已就绪”：

- 没有真实跑过 `scripts/watchdog_external_integration_smoke.py` 或关键 target；
- `feishu-control` 因未配置变量而 `skipped`，却被当作控制面已打通；
- provider 仅写入环境变量，但没有验证真实请求或失败回退；
- 把 preview route 的可调用性写成 Memory Hub 已完成主链接管；
- resident expert replay、session directory 与 health 之间任何一处证据缺失，却仍声称监督链已验收闭环；
- session directory 已经显示 `resident_expert_coverage=degraded` 或 stale expert，但 `healthz` / ops 仍被写成 green；
- 外部 Feishu 组织安装、域名、证书、密钥轮换尚未完成，却被写成仓库已自动闭环。

推荐结论口径只有两种：

- “repo 内 contract 已落地，真实环境接线已按本 runbook 验收通过”；
- “repo 内 contract 已落地，但真实环境仍受外部平台/凭证/组织安装阻断”。
