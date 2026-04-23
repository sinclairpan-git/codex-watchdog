# Spec：081-autonomous-next-step-recovery

## 背景

`WI-080` 已完成 live acceptance truth-boundary 的文档收口，但 resident orchestrator 的下一条主风险仍在运行时闭环上：

- `context_critical` 场景下，brain 已有 `propose_recovery`、`execute_recovery`、`resume_or_new_thread` 等恢复链路能力，但 resident policy 与 orchestrator 的自动执行判定没有完全对齐，导致超限后常停在“请求批准”，而不是自动续跑；
- next-step 语义在 brain provider、policy projection、session spine action surface 之间存在旧字段与新字段并存的问题，容易让 `continue_session` / `execute_recovery` 的判定语义漂移；
- 飞书进展投递虽然已有 summary 机制，但需要正式把“多项目可见性”和“不能只覆盖第一个项目”的回归冻结到 `WI-081` owner 下。

本工单的目标是把已经提交的 autonomous next-step 主补丁纳入 formal AI-SDLC owner，并继续完成余下的 runtime acceptance 收口，而不是把刚完成的改动继续挂在已关闭的 `WI-080` 名下。

## 范围

### In Scope

- formalize `WI-081` 的 owner、spec/plan/tasks 与 `.ai-sdlc` state 映射；
- 收口 brain `next_step` / `runtime_disposition` / session spine action 的语义对齐；
- 冻结 `propose_recovery` 在 brain 决策下可自动执行、而手工 `execute_recovery` 仍需要人工闸门的 contract；
- 冻结多项目 progress summary / Feishu delivery 的回归覆盖；
- 为后续 live runtime acceptance 留出明确的下一步任务入口与验证命令。

### Out of Scope

- 不在 `WI-081` 中引入新的外部平台依赖、真实组织安装或公网部署动作；
- 不重写 resident orchestrator 架构；
- 不把未跟踪的 `.cursor/`、`artifacts/` 或临时计划文档强行纳入本次代码提交；
- 不在没有新证据的情况下宣称真实环境联调已经完全闭环。

## Formal Source

- `src/watchdog/services/brain/models.py`
- `src/watchdog/services/brain/provider_runtime.py`
- `src/watchdog/services/brain/service.py`
- `src/watchdog/services/policy/decisions.py`
- `src/watchdog/services/policy/engine.py`
- `src/watchdog/services/session_spine/actions.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/services/delivery/envelopes.py`
- `src/watchdog/services/delivery/feishu_client.py`
- `tests/test_watchdog_brain_provider_runtime.py`
- `tests/test_watchdog_feishu_delivery.py`
- `tests/test_watchdog_policy_decisions.py`
- `tests/test_watchdog_policy_engine.py`
- `tests/test_watchdog_session_spine_api.py`
- `tests/test_watchdog_session_spine_runtime.py`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `.ai-sdlc/project/config/project-state.yaml`

## 非 Owner 约束

- **FR-8101**：`WI-081` 必须显式承接提交 `794ebbd` 引入的 autonomous next-step / recovery 语义，不得再把这些改动挂在已关闭的 `WI-080` 名下。
- **FR-8102**：自动执行只适用于 brain 决策产出的 `propose_recovery -> execute_recovery`；手工恢复入口仍需保留人工审批。
- **FR-8103**：`continue_session` 的人工闸门语义必须继续成立，不得因恢复自动化而被意外放宽。
- **FR-8104**：多项目 progress summary 回归必须验证至少两个项目的聚合可见性，避免只覆盖首个项目。

## 功能需求

- **FR-8105**：brain `next_step` 结构化字段、provider runtime 投影以及 policy decision 映射必须能稳定表达 `continue_session`、`execute_recovery` 与相应参数。
- **FR-8106**：resident orchestrator 的 `_decision_allows_auto_execute` 必须接受 `propose_recovery` 驱动的自动恢复，不得只识别 `propose_execute`。
- **FR-8107**：`tests/test_watchdog_policy_engine.py`、`tests/test_watchdog_policy_decisions.py`、`tests/test_watchdog_session_spine_runtime.py` 必须冻结“脑决策恢复可自动执行、手工恢复仍需审批”的 contract。
- **FR-8108**：`tests/test_watchdog_feishu_delivery.py` 必须冻结多项目 progress summary 的聚合交付 contract。
- **FR-8109**：在 `WI-081` 活跃期间，`.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/state/resume-pack.yaml` 与当前分支必须共同指向 `081-autonomous-next-step-recovery`。

## 验证要求

- `uv run pytest tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_feishu_delivery.py -q`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
