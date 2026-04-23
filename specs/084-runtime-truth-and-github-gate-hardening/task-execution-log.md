# Task Execution Log：084-runtime-truth-and-github-gate-hardening

- 2026-04-19：在 `WI-083` closeout 后继续审查 framework truth，发现当前工作树已经累积了一批未 formalize 的 guardrail 变更：runtime truth integrity、atomic runtime write contract、CI gate workflow contract、GitHub branch protection contract 与独立 audit workflow。
- 2026-04-19：确认这些改动不属于 `WI-083` residual closeout，也不是新的产品功能票，因此新建并切换到 `codex/084-runtime-truth-and-github-gate-hardening`，由 `WI-084` 独立承接。
- 2026-04-19：按 TDD 补 runtime truth 与 CLI 回归：新增 `tests/test_ai_sdlc_reconciliation.py` 覆盖 completed runtime stale `current_task`、非法 stage、invalid YAML、leftover temp file 与 active WI 选择护栏；新增 `tests/test_ai_sdlc_repo_cli.py` 覆盖 runtime truth / runtime write / CI gate / branch protection CLI gate 与独立 `verify github-branch-protection` 入口。
- 2026-04-19：新增 `src/watchdog/validation/ai_sdlc_runtime_io.py` 与 `tests/test_ai_sdlc_runtime_io.py`，冻结 `runtime.yaml` 必须通过 `write_yaml_atomic()` 原子替换写入，并验证 replace 失败时保留旧快照且不残留 `.tmp` 文件。
- 2026-04-19：新增 `src/watchdog/validation/ai_sdlc_runtime_write_contracts.py` 与 `tests/test_ai_sdlc_runtime_write_contracts.py`，对 `src/`、`ai_sdlc/`、`scripts/` 做 AST 扫描，阻断未经授权的 `runtime.yaml` 写入口；同时把 `scripts/reconcile_ai_sdlc_state.py` 切到 shared atomic writer。
- 2026-04-19：增强 `src/watchdog/validation/ai_sdlc_reconciliation.py`：runtime truth 改为按 YAML 解析与 allowlist 校验，active WI 选择忽略 invalid / close / archived runtime，并修复仓库内 `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/runtime.yaml` 的 completed stale `current_task` 漂移样本。
- 2026-04-19：新增 `src/watchdog/validation/ci_gate_contracts.py` 与 `tests/test_ci_gate_contracts.py`，冻结 `.github/workflows/pr-gate.yml` 的 `pull_request + push(main)`、`verify-constraints` / `test` / `lint` jobs、`needs` 依赖及 bypass-control 禁止项。
- 2026-04-19：新增 `src/watchdog/validation/github_branch_protection_contracts.py`、`.github/branch-protection.main.json`、`.github/workflows/branch-protection-audit.yml` 以及对应测试，冻结 `main` branch protection contract，并提供独立的 `gh api` live drift check。
- 2026-04-19：更新 `ai_sdlc/cli.py`、`src/watchdog/validation/__init__.py` 与 `README.md`，把新的 static contract checks 接入 `verify constraints`，同时公开 `python -m ai_sdlc verify github-branch-protection` operator 入口，并明确该 live audit 不挂到 PR gate。
- 2026-04-19：验证通过：
  - `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_runtime_io.py tests/test_ai_sdlc_runtime_write_contracts.py tests/test_ci_gate_contracts.py tests/test_github_branch_protection_audit_workflow.py tests/test_github_branch_protection_contracts.py tests/test_m3_agent_approvals.py tests/test_watchdog_external_integration_smoke.py`
  - `uv run pytest -q`
  - `uv run ruff check`
  - `uv run python -m ai_sdlc verify constraints`
  - `uv run python -m ai_sdlc verify github-branch-protection`
  - `uv run python -m ai_sdlc status`
