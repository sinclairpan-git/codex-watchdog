# 任务分解：014-stable-supervision-evaluation

> 对应规格：`specs/014-stable-supervision-evaluation/spec.md`
>
> 对应总设计：`docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 14.1 稳定 supervision 契约与版本推进

- **任务编号**：T141
- **状态**：未开始
- **依赖**：无
- **文件**：`src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py`, `tests/test_watchdog_session_spine_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `ActionCode.evaluate_supervision` 与 `ReplyCode.supervision_evaluation`；
  2. 存在 `SupervisionReasonCode` 与 `SupervisionEvaluation`；
  3. `WatchdogActionResult` 可稳定承载 `supervision_evaluation`；
  4. session spine `schema_version` 明确推进到 `2026-04-05.014`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py`

### Task 14.2 L2 supervision evaluation 内核

- **任务编号**：T142
- **状态**：未开始
- **依赖**：T141
- **文件**：`src/watchdog/services/session_spine/supervision.py`, `src/watchdog/services/session_spine/actions.py`, `src/watchdog/services/status_analyzer/stuck.py`, `tests/test_watchdog_supervision_evaluation.py`, `tests/test_watchdog_action_idempotency.py`
- **可并行**：否
- **验收标准**：
  1. supervision evaluation 继续复用 `evaluate_stuck(...)` 与 repo activity 抑制逻辑；
  2. `filesystem_activity_recent`、`within_threshold`、`no_last_progress_at` 都返回稳定 `SupervisionEvaluation`，且 `effect=noop`；
  3. `stuck_soft` 路径返回 `effect=steer_posted`，并只调用一次 `post_steer`；
  4. 相同幂等键重试返回相同 `WatchdogActionResult`，不会重复发起 steer。
- **验证**：`uv run pytest -q tests/test_watchdog_supervision_evaluation.py tests/test_watchdog_action_idempotency.py`

### Task 14.3 Stable API Surface + legacy evaluate compatibility shell

- **任务编号**：T143
- **状态**：未开始
- **依赖**：T142
- **文件**：`src/watchdog/api/session_spine_actions.py`, `src/watchdog/api/supervision.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_m2_watchdog_supervision.py`
- **可并行**：否
- **验收标准**：
  1. canonical `POST /api/v1/watchdog/actions` 支持 `action_code=evaluate_supervision`；
  2. 存在 alias route `POST /api/v1/watchdog/sessions/{project_id}/actions/evaluate-supervision`；
  3. legacy `POST /api/v1/watchdog/tasks/{project_id}/evaluate` 内部复用稳定 evaluation 内核，但继续保持基础 envelope 兼容；
  4. canonical 与 alias 对同一 action 返回相同语义 payload，legacy route 不被重新定义为 stable contract。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_m2_watchdog_supervision.py`

## Batch 2

### Task 14.4 OpenClaw adapter 接入 evaluate_supervision

- **任务编号**：T144
- **状态**：未开始
- **依赖**：T143
- **文件**：`src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `src/watchdog/services/adapters/openclaw/reply_model.py`, `tests/test_watchdog_openclaw_adapter.py`
- **可并行**：否
- **验收标准**：
  1. adapter 支持 `evaluate_supervision` intent；
  2. adapter 返回 `ReplyModel(reply_code=supervision_evaluation)`，且 `action_result.supervision_evaluation` 存在；
  3. adapter 不直连 legacy `/watchdog/tasks/{project_id}/evaluate`；
  4. adapter 对同一幂等键重试不会导致第二次 steer。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py`

### Task 14.5 文档与 OpenAPI 收口

- **任务编号**：T145
- **状态**：未开始
- **依赖**：T143
- **文件**：`README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `specs/014-stable-supervision-evaluation/spec.md`
- **可并行**：是
- **验收标准**：
  1. 文档明确 canonical stable surface 为 `WatchdogAction(action_code=evaluate_supervision)`；
  2. 文档明确 alias route 只是 wrapper，legacy `evaluate` 只是 compatibility shell；
  3. 文档明确 014 不做常驻 supervisor、历史回补或阈值 override；
  4. OpenAPI 暴露 canonical / alias / legacy 三类入口，并标明 stable vs legacy 角色。
- **验证**：人工核对 + `rg -n "evaluate_supervision|supervision_evaluation|evaluate-supervision|/watchdog/tasks/\\{project_id\\}/evaluate|legacy" README.md docs/getting-started.zh-CN.md docs/openapi/watchdog.json`

### Task 14.6 集成、receipt 非回归与 legacy 非回归收口

- **任务编号**：T146
- **状态**：未开始
- **依赖**：T144, T145
- **文件**：`tests/integration/test_openclaw_integration_spine.py`, `tests/test_watchdog_action_receipts.py`, `tests/test_watchdog_action_idempotency.py`, `tests/test_watchdog_session_spine_api.py`
- **可并行**：否
- **验收标准**：
  1. `evaluate_supervision` 执行后可通过 stable receipt query 读回相同结果；
  2. HTTP canonical route、adapter 与 receipt lookup 三者对同一 supervision result 一致；
  3. legacy `evaluate` 继续存在，且不会因 014 破坏既有 `progress / approvals / recover / events` 的基础兼容；
  4. `continue_session` 与 `execute_recovery` 既有 stable 行为不回归。
- **验证**：`uv run pytest -q tests/integration/test_openclaw_integration_spine.py tests/test_watchdog_action_receipts.py tests/test_watchdog_action_idempotency.py tests/test_watchdog_session_spine_api.py`
