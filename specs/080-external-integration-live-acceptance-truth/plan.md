# Plan：080-external-integration-live-acceptance-truth

## 目标

把真实环境联调 runbook 里“repo 内 contract 已落地”和“外部平台已验收通过”的边界冻结成 repo-local docs contract，同时清理 framework defect backlog 中已经被 `WI-079` 关闭的过时状态描述。

## 实施边界

1. 先 formalize `WI-080`，冻结 live acceptance truth-boundary 的 owner、范围与验证入口。
2. 在不改动运行时的前提下，补强 `docs/operations/external-integration-live-acceptance.md` 的边界表述，并把这些表述纳入 `src/watchdog/validation/docs_contracts.py`。
3. 扩展 `tests/test_long_running_autonomy_doc_contracts.py`，确保新的 docs contract 受回归保护。
4. 同步 `docs/framework-defect-backlog.zh-CN.md` 的 `FD-004` 状态，并完成 `.ai-sdlc` state / mirror closeout。

## 验证

- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
