# Spec：083-feishu-discovery-session-directory-routing

## 背景

`WI-082` 在真实环境执行 `feishu-discovery` smoke 时，命中了一个新的 residual blocker：发送多项目目录查询文本后，运行时返回的是 `goal_contract_bootstrap`，而不是文档和 repo-local contract 规定的 `command_request + list_sessions/session_directory`。这说明当前风险已经从“验收证据是否记录完整”切换为“Feishu discovery 文本入口在真实环境下没有稳定落到 session-directory 读路径”。

仓库内已有明确 contract 与回归面：

- `docs/getting-started.zh-CN.md` 与 `docs/operations/external-integration-live-acceptance.md` 都要求 `feishu-discovery` 文本事件真正落到 `list_sessions/session_directory`；
- `tests/test_watchdog_feishu_ingress.py`、`tests/test_watchdog_external_integration_smoke.py`、`tests/test_watchdog_session_spine_api.py` 与 `tests/integration/test_openclaw_integration_spine.py` 已冻结 repo-local 读面与消息入口语义；
- 真实环境却返回 `goal_contract_bootstrap`，说明需要一张新的 formal owner 单独承接路由/部署/语义漂移问题，而不能继续塞进 `WI-082` 的验收 closeout。

因此 `WI-083` 的目标是正式承接 **Feishu discovery session-directory routing residual**：冻结这条入口的 contract、核对 repo-local 与 live runtime 的差异来源，并把修复与复验落成独立 evidence 链。

## 范围

### In Scope

- formalize `WI-083` 的 owner、`spec / plan / tasks / task-execution-log` 与 `.ai-sdlc/work-items/083-*` mirror；
- 冻结 `feishu-discovery` 的正式 contract：文本入口、`intent_code=list_sessions`、`reply_code=session_directory`、返回项目集合与 `resident_expert_coverage` 读面；
- 调查并修复导致真实环境返回 `goal_contract_bootstrap` 的路由/识别/部署漂移；
- 以 targeted verification 与 live smoke 复验 `feishu-discovery`，并把结果沉淀为 fail-closed 证据；
- 回写 residual ledger，明确 `WI-082` 的 blocker 已由 `WI-083` 正式承接。

### Out of Scope

- 不重开 `WI-082` 的 live runtime acceptance closeout；
- 不新增新的 Feishu smoke target，也不修改 `feishu-control` 的 `goal_contract_bootstrap` contract；
- 不改写 session-directory 的业务语义、resident expert coverage 计算逻辑或多项目目录展示格式，除非修复 discovery 路由必须依赖既有 contract 对齐；
- 不把外部组织安装、凭证发放、域名证书等仓库外条件伪装为 repo-local 已闭环。

## Formal Source

- `docs/getting-started.zh-CN.md`
- `docs/operations/external-integration-live-acceptance.md`
- `src/watchdog/services/feishu_ingress/service.py`
- `src/watchdog/services/adapters/openclaw/intents.py`
- `src/watchdog/services/adapters/openclaw/adapter.py`
- `src/watchdog/api/session_spine_queries.py`
- `src/watchdog/validation/external_integration_smoke.py`
- `tests/test_watchdog_feishu_ingress.py`
- `tests/test_watchdog_external_integration_smoke.py`
- `tests/test_watchdog_session_spine_api.py`
- `tests/integration/test_openclaw_integration_spine.py`
- `docs/architecture/long-running-residual-backlog-ledger.yaml`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `.ai-sdlc/project/config/project-state.yaml`

## 非 Owner 约束

- **FR-8301**：`WI-083` 只处理 `feishu-discovery` 到 `session_directory` 的 residual blocker，不得顺手扩张为新的 Feishu 控制面或 Brain/goal bootstrap 改造票。
- **FR-8302**：若真实环境问题最终来自部署漂移、旧版本服务或外部配置差异，必须按 fail-closed 记录证据，不能用 repo-local 绿测替代 live runtime 结论。
- **FR-8303**：`goal_contract_bootstrap` 仍是 `feishu-control` 的正确 contract；`WI-083` 只能修 discovery 入口误路由，不得破坏现有 goal bootstrap 行为。
- **FR-8304**：`WI-083` 必须把 `WI-082` 中发现的 blocker 单独记账，并在 residual ledger 中留下 formal owner 关联。

## 功能需求

- **FR-8305**：对于 discovery 文本（默认 `项目列表` 或 `所有项目进展`），Feishu ingress 必须稳定产出 `command_request`，其 `data.intent_code=list_sessions`、`data.reply_code=session_directory`。
- **FR-8306**：discovery 响应必须继续返回 `sessions`、`progresses`、`message` 与 `resident_expert_coverage` 等既有 contract 字段，且项目集合要覆盖 smoke 中声明的 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS`。
- **FR-8307**：repo-local 回归必须覆盖 discovery 文本别名与 routing contract，避免 `所有项目进展` 在某些路径下被重新识别为 goal bootstrap。
- **FR-8308**：`WI-083` 激活后，`.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/state/resume-pack.yaml`、`.ai-sdlc/project/config/project-state.yaml` 与当前分支必须共同指向 `083-feishu-discovery-session-directory-routing`，且 `next_work_item_seq` 前滚为 `84`。

## 验证要求

- `uv run pytest -q tests/test_watchdog_feishu_ingress.py tests/test_watchdog_external_integration_smoke.py tests/test_watchdog_session_spine_api.py::test_session_directory_route_surfaces_resident_expert_coverage tests/integration/test_openclaw_integration_spine.py::test_integration_session_directory_api_and_adapter_share_resident_expert_coverage`
- `set -a; source .env.w; export WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS="openclaw-codex-watchdog,Ai_AutoSDLC,meeting,portal"; set +a; uv run python scripts/watchdog_external_integration_smoke.py --target feishu-discovery`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
