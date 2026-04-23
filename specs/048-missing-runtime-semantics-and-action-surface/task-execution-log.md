# 执行日志：048-missing-runtime-semantics-and-action-surface

## 2026-04-16

### Phase 1：scope recovery / formal docs freeze

- 基于 `WI-047` 生成的 `matrix-owner-ledger.yaml`，已把 owner=`WI-048` 的 22 条矩阵行提取为当前 work item 的固定边界。
- 当前收紧后的 048 边界：
  - 只做 canonical task status / phase、stable action surface、fail-closed approval boundary 与 `Memory Hub` hot-path runtime semantics；
  - 不进入 `WI-049` 的飞书/Feishu/natural-language 主入口闭环；
  - 不进入 `WI-050` 的性能/重启/安全/可靠性/交付物验收；
  - 不允许通过 README、summary、prompt 文案或 example 冒充 runtime semantics closure。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/048-*` 基线。
- 当前 canonical branch 已切到 `codex/048-missing-runtime-semantics-and-action-surface`。
- 当前下一执行入口暂定为 `T481`：先完成 formal docs 与对抗评审，再决定是否进入 `T482` 的 red test。

### Phase 1：adversarial review closeout

- 已完成 Anthropic Manager Expert 与 Hermes Agent Expert 两轮对抗评审，最终结论均为 `APPROVED`，无 blocking / P1 / P2 残留。
- 已按评审意见补齐：
  - `matrix-row-0013 / 0015 / 0017` 只定义 semantic effect，渠道绑定继续留给 `WI-049`；
  - canonical action/status transition contract、guard 与非法转移拒绝语义；
  - `Memory Hub` 与 `Session Service + Goal Contract` 的 precedence / conflict degrade contract；
  - `docs_baseline_ref` 的 deterministic hash recipe（固定路径、顺序、`LF` 归一化、`<<<PATH:...>>>` 标签与 `SHA-256` 构造）。
- 已按 deterministic hash recipe 固定 reviewed formal artifact set 的 baseline，并把 `docs_baseline_ref` 写入 runtime / resume / checkpoint 元数据；评审完成时间为 `2026-04-16T07:28:53Z`。
- 当前 `T481` 正式收口，下一执行入口切换为 `T482`：先写失败测试锁定 runtime semantics contract，再进入实现。

### Phase 2：red tests freeze runtime semantics contract

- 已新增 `tests/test_watchdog_runtime_semantics.py`，冻结 canonical status/phase normalize、`continue` guard rejection 与 `failed` terminal semantics。
- 已扩展 `tests/test_watchdog_action_execution.py`、`tests/test_watchdog_steer.py`、`tests/test_a_control_agent.py`、`tests/test_watchdog_memory_hub.py` 与 `tests/test_watchdog_memory_degradation.py`，覆盖 stable action code 扩展、steer template registry、risk fail-closed 与 `Memory Hub` runtime advisory context。
- 首轮 red 验证结果为 `9 failed, 25 passed`，失败点全部对应缺失 contract：
  - `normalize_task_status / normalize_task_phase / validate_action_transition` 缺失；
  - `ActionCode` 缺少 `pause_session / resume_session / summarize_session / force_handoff / retry_with_conservative_path`；
  - steer template registry 缺失；
  - risk classifier 对 workspace/network/publish 未 fail closed；
  - `MemoryHubService.build_runtime_advisory_context()` 缺失。
- 已按 TDD 最小实现补齐上述 contract，green 验证结果为 `34 passed in 0.60s`。
- 当前 `T482` 正式收口，下一执行入口切换为 `T483`：继续把 action handler、alias route 与 runtime effect/receipt 收口为稳定 surface。

### Phase 3：stable action surface closeout

- 已为 `pause / resume / summarize / force_handoff / retry_with_conservative_path` 补齐 canonical action handler，并把 alias route 收口到 `session_spine_actions`：
  - `/api/v1/watchdog/sessions/{project_id}/actions/pause`
  - `/api/v1/watchdog/sessions/{project_id}/actions/resume`
  - `/api/v1/watchdog/sessions/{project_id}/actions/summarize`
  - `/api/v1/watchdog/sessions/{project_id}/actions/force-handoff`
  - `/api/v1/watchdog/sessions/{project_id}/actions/retry-with-conservative-path`
- 已扩展 `ActionCode / Effect / AControlAgentClient`，新增 `session_paused / session_resumed / summary_generated / conservative_retry_requested` 等 canonical effect，并补齐 runtime 侧 `/api/v1/tasks/{project_id}/pause` runtime path。
- `continue`、`resume` 与 `force_handoff` 仍复用既有 steer / recovery / handoff hot path，没有新增旁路执行器。
- T483 回归验证通过：
  - `uv run pytest -q tests/test_watchdog_runtime_semantics.py tests/test_watchdog_action_execution.py tests/test_watchdog_steer.py tests/test_a_control_agent.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_degradation.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_session_spine_contracts.py tests/integration/test_feishu_integration_spine.py tests/test_m2_stuck.py`
  - 结果：`118 passed in 2.41s`

### Phase 4：fail-closed boundary 与 Memory Hub hot path closeout

- 已把 risk classifier 扩展为显式 fail-closed boundary：
  - workspace：`../`、`..\\`
  - network：`ssh / scp / rsync / ftp / telnet / http(s) / permissions:network.*`
  - system：`sudo / launchctl / /etc/`
  - credential：`token / secret / credential / api_key / password`
  - destructive：`rm -rf`
  - publish：`git push / publish / deploy / release`
- 已验证 `CodexAppServerBridge` 对 `network.http + credentials.read` 组合型 permission request 默认进入 human gate，而不是继续 `policy-auto`。
- `BrainDecisionService` 与 `perform_recovery_execution()` 已接入 `Memory Hub` advisory context：
  - decision / recovery 热路径都会构造 runtime advisory context；
  - `Memory Hub` 不可用时写入 `memory_unavailable_degraded`；
  - `Memory Hub` 与 session truth 冲突时写入 `memory_conflict_detected`；
  - 所有降级都保持 `Session Service + Goal Contract` 优先，不覆盖 canonical truth。
- T484 回归验证通过：
  - `uv run pytest -q tests/test_a_control_agent.py tests/test_codex_app_server_bridge.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_degradation.py`
  - 结果：`37 passed in 0.53s`

### Phase 5：048 closeout / handoff

- 组合回归已通过：
  - `uv run pytest -q tests/test_watchdog_recovery_execution.py tests/test_watchdog_action_execution.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_session_spine_runtime.py tests/test_a_control_agent.py tests/test_codex_app_server_bridge.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_degradation.py`
  - 结果：`147 passed in 4.57s`
- 当前 `WI-048` 正式完成，下一执行入口固定为 `WI-049`。
- `WI-049` 只负责 Feishu / Feishu / natural-language 主入口与语义路由绑定，必须直接消费 048 已冻结的 canonical runtime surface，不得重新定义状态、动作或 Memory precedence contract。
