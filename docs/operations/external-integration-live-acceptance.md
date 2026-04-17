# External Integration Live Acceptance

这份 runbook 只定义真实环境联调与验收步骤，用来确认仓库内已经实现的外部契约能在 staging / production-like 环境被正确接线。

边界固定如下：

- 它不是新的 product work item，也不替代 `.ai-sdlc/` 的正式 backlog。
- 它不声明外部组织安装、域名、凭证发放已经自动完成。
- 它不替代 `docs/operations/release-gate-runbook.md`；release gate 与 live acceptance 必须同时成立，才能对外声称“当前接线就绪”。
- 它不是 production acceptance gate；外部平台最终放量、组织级权限开通、正式公网入口与密钥轮换仍属于仓库外运维真值。

## Preconditions

执行这份 runbook 前，至少确认：

1. Watchdog 已部署，并且 `GET /healthz` 可达。
2. 真实环境的 `WATCHDOG_API_TOKEN` 已配置完成，且可用于受保护接口。
3. 若要验收 Feishu 官方入口，外部自建应用、事件订阅 URL、verification token 与 receive id 已在平台侧配置。
4. 若要验收 OpenAI-compatible provider，`base_url`、`api_key`、`model` 已在真实环境中完成注入。
5. 若要验收 Memory Hub preview，调用方已明确接受它仍是 preview contract，而非 runtime source of truth。

## Required Configuration Surface

最小环境变量面如下；允许通过密钥管理或部署平台注入，但验收时必须确认这些值确实存在于运行环境：

### Watchdog base

- `WATCHDOG_BASE_URL`
- `WATCHDOG_API_TOKEN`

### Feishu official ingress and direct delivery

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

### Memory Hub preview toggle

- `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=true|false`

### Optional Feishu callback contract smoke inputs

- `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`

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

### 2. Feishu official callback verification

先验证官方事件入口 `POST /api/v1/watchdog/feishu/events` 的 `url_verification` 契约：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target feishu
```

必要时可手工复验：

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

- 响应回显 `challenge`；
- 验证 token 正确时不出现 schema drift；
- 若 Feishu 平台侧仍未安装或回调地址未生效，应标记为外部平台 blocker，而不是仓库功能缺失。

### 3. Feishu control-plane DM contract

若真实环境要让控制面通过 Feishu DM 触发目标收敛，继续执行：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-control
```

这一项会向 `POST /api/v1/watchdog/feishu/events` 发送 `im.message.receive_v1` 文本事件，消息体固定为：

```text
repo:<project_id> /goal <goal_message>
```

通过标准：

- 结果不是 `skipped` 时，必须落成 `goal_contract_bootstrap`；
- 若设置了 `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`，返回 session id 必须一致；
- 如果变量未配置而出现 `skipped`，这只能说明真实 DM smoke 尚未执行，不能当作控制面已验收完成；
- 若真实用户在 Feishu 中直接发送同格式 DM，也应触发相同 contract，而不是另一套私有入口。

### 4. OpenAI-compatible provider wiring

切换到通用的 OpenAI-compatible provider 后执行：

```bash
uv run python scripts/watchdog_external_integration_smoke.py --target provider
```

建议同时做一条低风险真实调用，确认请求确实发向目标 provider。

通过标准：

- `WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible` 已生效；
- provider smoke 返回 `passed`；
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
uv run python scripts/watchdog_external_integration_smoke.py --target provider
uv run python scripts/watchdog_external_integration_smoke.py --target memory
uv run python scripts/watchdog_external_integration_smoke.py \
  --target feishu-control \
  --target provider \
  --target memory \
  --markdown-report artifacts/watchdog-live-acceptance.md
```

通过标准：

- 默认 smoke 至少覆盖 `health`、`feishu`、`provider`、`memory`；
- `feishu-control` 在真实环境若需要控制面 DM，则应单独跑到 `passed`；
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
8. 若执行了 Memory preview，记录 `enabled=true|false` 与 `contract_name=ai-autosdlc-cursor`。

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
- 外部 Feishu 组织安装、域名、证书、密钥轮换尚未完成，却被写成仓库已自动闭环。

推荐结论口径只有两种：

- “repo 内 contract 已落地，真实环境接线已按本 runbook 验收通过”；
- “repo 内 contract 已落地，但真实环境仍受外部平台/凭证/组织安装阻断”。
