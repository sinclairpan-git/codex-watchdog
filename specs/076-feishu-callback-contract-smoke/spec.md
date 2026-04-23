# Spec：076-feishu-callback-contract-smoke

## 背景

`WI-075` 已把外部集成 smoke harness 的基础四项能力正式收口进 `ai_sdlc` 真值，但仓库内仍存在一个 repo-local 验收缺口：

- 默认 smoke 只能验证 Feishu `url_verification` contract；
- `docs/getting-started.zh-CN.md` 已把 Feishu DM `/goal ...` 归一到 official ingress 作为正式控制面步骤的一部分；
- 现有脚本还不能对这条 callback normalization 路径做可回归的最小 smoke。

因此本工单的目标不是重开真实 Feishu 组织级接入或生产级 E2E，而是在既有 `/api/v1/watchdog/feishu/events` 入口上补一条 **可选、repo-local、可回归** 的 callback contract smoke，验证最小 `im.message.receive_v1` 文本事件能被归一到 `goal_contract_bootstrap`。

在强制全量验证过程中，还暴露了一个与本次交付并行的 release blocker：`POST /api/v1/watchdog/feishu/responses` 在重复提交同一 response tuple 时，会因为 compatibility receipt event 的动态时间戳而触发 session event idempotency 冲突。该问题阻断全量回归，因此需要在本工单内一并修复。

## 范围

### In Scope

- 为 external integration smoke harness 新增可选 target：`feishu-control`
- 通过最小 `im.message.receive_v1` DM 文本事件验证 official ingress -> `goal_contract_bootstrap` 的 callback contract
- 为该可选 target 增补 smoke 专用环境变量、操作文档与 docs contract
- 保持默认 `all` 仍只覆盖基础四项，不把可选 target 强行变成必跑项
- 修复 `feishu/responses` compatibility receipt replay 的幂等冲突，确保全量测试恢复为绿色
- 正式把以上交付收口为 `WI-076`

### Out of Scope

- 不接入真实 Feishu 组织安装、真实回调地址、真实 DM 外网投递
- 不把 `feishu-control` 扩展成生产巡检、release orchestrator 或多步骤 E2E
- 不新增新的 runtime settings 字段或新的 API route
- 不把 optional callback smoke 改写成 `/api/v1/watchdog/feishu/control` 的另一条主控面验收

## Formal Source

- `docs/architecture/external-integration-smoke-harness-design.md`
- `src/watchdog/validation/external_integration_smoke.py`
- `scripts/watchdog_external_integration_smoke.py`
- `tests/test_watchdog_external_integration_smoke.py`
- `src/watchdog/api/feishu_responses.py`
- `tests/test_watchdog_approval_loop.py`
- `README.md`
- `docs/getting-started.zh-CN.md`
- `config/examples/watchdog.env.example`

## 非 Owner 约束

- **FR-7601**：`feishu-control` 必须保持为可选 target，默认 `all` 不得被隐式扩成需要 project binding 的五项检查。
- **FR-7602**：callback smoke 只能复用既有 `/api/v1/watchdog/feishu/events` official ingress，不得新建平行入口。
- **FR-7603**：smoke 专用环境变量只能服务于该可选 target，不得污染运行时 settings 契约。
- **FR-7604**：full-suite 回归必须恢复为全绿，不能留下“定向测试通过、全量测试失败”的收口状态。

## 功能需求

- **FR-7605**：`external_integration_smoke` 必须支持 `feishu-control` target，并在收到 `all + feishu-control` 时把可选 target 追加到基础四项之后执行。
- **FR-7606**：`feishu-control` 必须构造最小 `im.message.receive_v1` DM 文本事件，消息内容为 `repo:<project_id> /goal <goal_message>`。
- **FR-7607**：`feishu-control` 的成功判定必须至少断言 `accepted=true`、`event_type=goal_contract_bootstrap`、`project_id` 匹配、`session_id` 非空、`goal_contract_version` 非空。
- **FR-7608**：若 `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID` 或 `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE` 未配置，则 `feishu-control` 必须返回 `skipped(feature_not_configured)`，而不是让默认 smoke 失败。
- **FR-7609**：README、getting-started、env example、architecture design 与 docs contract 必须同步可选 callback smoke 的新入口。
- **FR-7610**：`feishu/responses` 对相同 response tuple 的重复提交，必须保持 compatibility receipt 事件幂等，不得再因为动态时间戳引发 session event 冲突。

## 验证要求

- `uv run pytest -q tests/test_watchdog_external_integration_smoke.py tests/test_long_running_autonomy_doc_contracts.py tests/test_watchdog_feishu_ingress.py`
- `uv run pytest -q tests/test_watchdog_approval_loop.py::test_feishu_response_api_uses_response_tuple_as_idempotency_key`
- `uv run pytest -q`
- `uv run ruff check src/watchdog/api/feishu_responses.py src/watchdog/validation/external_integration_smoke.py scripts/watchdog_external_integration_smoke.py tests/test_watchdog_external_integration_smoke.py src/watchdog/validation/docs_contracts.py tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
