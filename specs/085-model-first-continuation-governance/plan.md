# Plan：085-model-first-continuation-governance

## 目标

把自动推进链路从“session 级窄上下文 + 规则触发恢复”升级为“项目级 model-first continuation governance”，使系统能基于 authoritative project / branch / progress truth 正确判断：

- 继续当前分支；
- 恢复当前分支；
- 当前分支完成并切到下一分支/下一工单；
- 项目整体完成并停止自动推进；
- 或因审批 / 冻结 / stale truth 被 fail-closed 阻断。

## 实施边界

1. 先 formalize `WI-085` 的 owner、spec / plan / tasks 与 `.ai-sdlc` active state，对齐当前 branch 与下一 work item 入口，结束 `WI-084` 已 completed 但运行时问题仍外溢的状态。
2. 先写失败测试，冻结 `PCDI` authoritative snapshot contract、continuation decision v3 schema、project execution state、pending approval hard gate、terminal suppression、fallback invalidation、continuation identity / branch switch token 生命周期与 packet render contract。
3. 再最小实现 `PCDI` builder、project-level execution state、pending approval hard gate、terminal suppression 与 fallback reuse invalidation，确保 fail-closed gate 先于任何 packet / adapter 行为落地。
4. 在硬门到位后，先单独落 lineage / provenance 写面，要求所有 gate verdict、suppression、identity/token issuance / consume / invalidate、packet replay 都可审计、可回放。
5. 再实现 eligibility gate、routing gate、`continuation_identity`、`branch_switch_token` 的单次消费状态机，以及最小 operator control-plane projection。
6. 最后实现 `ContinuationPacket` 真值对象与 packet->markdown/adapter summary 的单向渲染契约，并把 recovery / handoff / orchestrator / adapter surface 切到 packet truth；渲染结果不得回流为 `latest-summary`、`PCDI`、routing input、dedupe 输入或模型输入。
7. 跑 targeted suites、integration、full suite、repo-local constraints 与 AI-SDLC status，确认不再重复发无意义 handoff summary，并能稳定区分 continue / switch / complete / block。

## 验证

- `uv run pytest -q tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py`
- `uv run pytest -q`
- `uv run ruff check`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
