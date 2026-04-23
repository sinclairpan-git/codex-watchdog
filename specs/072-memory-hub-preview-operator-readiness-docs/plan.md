# Plan：072-memory-hub-preview-operator-readiness-docs

## 目标

把 `ai-autosdlc-cursor` preview route 的 operator 启用方式补成仓库内正式可照抄的 env sample / getting-started / doc contract 真值。

## 实施边界

1. 先补 docs contract 断言，锁住 env sample 与 getting-started 中必须出现的 preview toggle / route / default-off 语义。
2. 再补 `watchdog.env.example` 与 `getting-started.zh-CN.md` 的启用说明和 smoke test。
3. 最后同步 `ai_sdlc` 元数据，并吸收双对抗评审 closeout。

## 验证

- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
