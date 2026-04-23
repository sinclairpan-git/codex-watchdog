# Spec：084-runtime-truth-and-github-gate-hardening

## 背景

`WI-083` 完成后，repo-local 与 live external integration 都已恢复稳定，但继续沿着 framework truth 做仓库内巡检时，又暴露出一组新的 guardrail 缺口，而且这些缺口已经真实落在当前工作树里：

- `.ai-sdlc/work-items/<wi>/runtime.yaml` 仍可能出现 completed mirror 残留 `current_task`、非法 `current_stage`、无效 YAML 或原子写临时文件残留，但现有 reconciliation 只做弱字符串读取，没有把这些 runtime truth 视为正式 blocker；
- 运行时 state 写面仍允许直接 `write_text()` / `open(..., "w")` 之类的 ad hoc 写入 `runtime.yaml`，缺少统一的 atomic writer contract；
- 仓库已开始承载 `.github/` 下的 CI / governance surfaces，但 repo-local `python -m ai_sdlc verify constraints` 还没有把 PR gate workflow、branch protection contract、branch protection audit workflow 作为正式静态约束；
- GitHub branch protection 需要 live drift check，但这个在线检查不应该混进 PR gate，而应作为独立的 operator/audit 入口。

这批问题都不是产品功能票，而是 **runtime truth + repository governance guardrails** 的 formal hardening。`WI-084` 因此只负责把这些 guardrails 正式收口为 canonical contract，并把当前仓库状态推进到与新约束一致。

## 范围

### In Scope

- formalize `WI-084` 的 owner、`spec / plan / tasks / task-execution-log` 与 `.ai-sdlc/work-items/084-*` mirror；
- 为 `.ai-sdlc/work-items/*/runtime.yaml` 增加 runtime truth integrity contract：允许阶段枚举、YAML 结构、`work_item_id` 对目录一致性、原子写临时文件残留等；
- 增加统一的 `runtime.yaml` atomic writer helper，并新增 repo-local validator，阻断 `src/`、`ai_sdlc/`、`scripts/` 下未授权的 runtime 写入口；
- 把 runtime truth / runtime write / CI gate / GitHub branch protection contract surfaces 接入 `python -m ai_sdlc verify constraints`；
- 新增独立的 `python -m ai_sdlc verify github-branch-protection` 在线校验入口，并冻结 `.github/branch-protection.main.json` 与 `.github/workflows/branch-protection-audit.yml`；
- 冻结 `.github/workflows/pr-gate.yml` 的最小 CI gate contract；
- 同步当前仓库 state truth，包括把顶层 `.ai-sdlc` 指针切到 `WI-084`，并修复已发现的 completed runtime stale `current_task` 漂移样本。

### Out of Scope

- 不修改任何产品业务语义、Feishu/Feishu runtime contract 或外部集成行为；
- 不把 branch protection live check 混进 PR gate，也不要求每个 PR workflow 都在线调用 GitHub branch protection API；
- 不重新设计 `.ai-sdlc/work-items/*/runtime.yaml` 的 schema，只在既有结构内补最小 fail-closed 约束；
- 不扩展 GitHub governance 到 CODEOWNERS、merge queue、required deployment 等当前仓库尚未冻结的策略。

## Formal Source

- `ai_sdlc/cli.py`
- `scripts/reconcile_ai_sdlc_state.py`
- `src/watchdog/validation/__init__.py`
- `src/watchdog/validation/ai_sdlc_reconciliation.py`
- `src/watchdog/validation/ai_sdlc_runtime_io.py`
- `src/watchdog/validation/ai_sdlc_runtime_write_contracts.py`
- `src/watchdog/validation/ci_gate_contracts.py`
- `src/watchdog/validation/github_branch_protection_contracts.py`
- `tests/test_ai_sdlc_reconciliation.py`
- `tests/test_ai_sdlc_repo_cli.py`
- `tests/test_ai_sdlc_runtime_io.py`
- `tests/test_ai_sdlc_runtime_write_contracts.py`
- `tests/test_ci_gate_contracts.py`
- `tests/test_github_branch_protection_audit_workflow.py`
- `tests/test_github_branch_protection_contracts.py`
- `.github/branch-protection.main.json`
- `.github/workflows/pr-gate.yml`
- `.github/workflows/branch-protection-audit.yml`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `.ai-sdlc/project/config/project-state.yaml`
- `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/runtime.yaml`

## 非 Owner 约束

- **FR-8401**：084 只处理 runtime truth 与 repo governance guardrails，不得顺手扩展为新的产品功能或集成验收票。
- **FR-8402**：084 必须把 branch protection live check 与 PR gate 静态约束明确分离；PR gate 只跑 repo-local checks，branch protection drift 由独立 audit 命令与 workflow 承担。
- **FR-8403**：084 不得通过“删文件绕过校验”的方式关闭问题；`.github/` contract 与 `runtime.yaml` truth 必须以保留正式 surface 的方式满足约束。
- **FR-8404**：084 可以修复已存在的 runtime mirror 漂移样本，但不得伪造不存在的 task 历史或 rewrite 已关闭 work item 的业务结论。

## 功能需求

- **FR-8405**：`collect_reconciliation_inventory()` 在推导 active work item 时，必须忽略 `current_stage=close|archived` 的 runtime mirror，并且不能让非法 stage、无效 YAML 或残留 temp file 的 runtime truth 抢占 active WI 判定。
- **FR-8406**：repo-local `validate_runtime_truth_integrity()` 必须在以下场景 fail-closed：`runtime.yaml` 非法 YAML、顶层不是 mapping、缺失或非法 `current_stage`、`current_stage` 不在 allowlist、`work_item_id` 与目录不一致、原子写临时文件残留。
- **FR-8407**：`runtime.yaml` 的正式写入口必须统一走 `watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic()`；`src/`、`ai_sdlc/`、`scripts/` 中若存在未授权的 runtime 写入口，`python -m ai_sdlc verify constraints` 必须失败。
- **FR-8408**：`scripts/reconcile_ai_sdlc_state.py` 在写 `runtime.yaml` 时必须复用统一 atomic writer，而不是继续直接 `write_text()`。
- **FR-8409**：repo-local `python -m ai_sdlc verify constraints` 必须把 runtime truth integrity、runtime write entrypoints、CI gate surfaces、branch protection contract surfaces 与 branch protection audit workflow surfaces 一并视为 blocker。
- **FR-8410**：仓库必须存在 `.github/workflows/pr-gate.yml`，并冻结最小 contract：无过滤 `pull_request`、`push: main`、`verify-constraints`/`test`/`lint` jobs 及其必需命令，且这些 required jobs/steps 不得通过 `if` 或 `continue-on-error` 绕过。
- **FR-8411**：仓库必须存在 `.github/branch-protection.main.json` 与 `.github/workflows/branch-protection-audit.yml`，并冻结 `main` 分支当前要求的 status checks、review count、linear history、conversation resolution、只读 workflow 权限与独立 hourly audit 入口。
- **FR-8412**：`python -m ai_sdlc verify github-branch-protection` 必须先校验静态 contract，再通过 `gh api repos/{owner}/{repo}/branches/{branch}/protection` 执行 live drift check；若 live drift 失败、返回非法 JSON 或字段不匹配，命令必须失败。
- **FR-8413**：`WI-084` closeout 后，`.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/state/resume-pack.yaml`、`.ai-sdlc/project/config/project-state.yaml` 与当前 branch 必须共同指向 `084-runtime-truth-and-github-gate-hardening`，且 `next_work_item_seq` 前滚为 `85`。

## 验证要求

- `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_runtime_io.py tests/test_ai_sdlc_runtime_write_contracts.py tests/test_ci_gate_contracts.py tests/test_github_branch_protection_audit_workflow.py tests/test_github_branch_protection_contracts.py tests/test_m3_agent_approvals.py tests/test_watchdog_external_integration_smoke.py`
- `uv run pytest -q`
- `uv run ruff check`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc verify github-branch-protection`
- `uv run python -m ai_sdlc status`
