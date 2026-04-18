# Plan：083-feishu-discovery-session-directory-routing

## 目标

把 `WI-082` 中暴露出的 `feishu-discovery -> goal_contract_bootstrap` 误路由问题正式拆成独立 owner，收口 discovery 文本入口到 `session_directory` 的 contract、修复路径，并完成 live smoke 复验。

## 实施边界

1. 先把当前分支与 `.ai-sdlc` 指针切到 `WI-083`，在 formal truth 中明确这是新 residual owner，而不是继续把 blocker 混写在 `WI-082`。
2. 冻结 discovery 文本入口的 contract：别名文案、intent 识别、reply code、项目集合、`resident_expert_coverage` 读面，以及 smoke 对这条路径的 fail-closed 判定。
3. 对照 repo-local 测试面与真实环境返回，定位 discovery 文本为何会落成 `goal_contract_bootstrap`；若是代码路径问题则修复代码，若是部署或环境漂移则补充证据与 operator 结论。
4. 跑 targeted verification 与 live `feishu-discovery` smoke，只有真正返回 `session_directory` 且项目集合满足预期时，才能把该 residual 标记为完成。

## 验证

- `uv run pytest -q tests/test_watchdog_feishu_ingress.py tests/test_watchdog_external_integration_smoke.py tests/test_watchdog_session_spine_api.py::test_session_directory_route_surfaces_resident_expert_coverage tests/integration/test_openclaw_integration_spine.py::test_integration_session_directory_api_and_adapter_share_resident_expert_coverage`
- `set -a; source .env.w; export WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS="openclaw-codex-watchdog,Ai_AutoSDLC,meeting,portal"; set +a; uv run python scripts/watchdog_external_integration_smoke.py --target feishu-discovery`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
