# Plan：084-runtime-truth-and-github-gate-hardening

## 目标

把 `.ai-sdlc/work-items/*/runtime.yaml`、repo-local constraint gate、CI workflow surfaces 与 GitHub branch protection audit 全部收口为可验证、可阻断的 formal contract，避免 runtime truth 与仓库治理面继续静默漂移。

## 实施边界

1. 先 formalize `WI-084`，冻结 runtime truth、runtime write、CI gate 与 branch protection 的 owner 边界，并把当前分支 / 顶层 `.ai-sdlc` 指针切到 084。
2. 先写失败测试，锁定 runtime truth integrity、atomic runtime write contract、CI gate workflow contract、branch protection static/live contract 与 CLI 入口语义。
3. 再最小实现 shared atomic writer、runtime truth validator、runtime write scan、CI gate validator、branch protection validator 以及 CLI 挂接。
4. 同步当前仓库的 governance surfaces 与 state truth，包括 `.github/` contract files、`037/runtime.yaml` 的 stale `current_task` 修复，以及 README/CLI 文档入口。
5. 跑 targeted suite、full suite、repo-local constraints 与 live branch protection audit，只有静态与在线证据都成立时，才能 closeout `WI-084`。

## 验证

- `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_runtime_io.py tests/test_ai_sdlc_runtime_write_contracts.py tests/test_ci_gate_contracts.py tests/test_github_branch_protection_audit_workflow.py tests/test_github_branch_protection_contracts.py tests/test_m3_agent_approvals.py tests/test_watchdog_external_integration_smoke.py`
- `uv run pytest -q`
- `uv run ruff check`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc verify github-branch-protection`
- `uv run python -m ai_sdlc status`
