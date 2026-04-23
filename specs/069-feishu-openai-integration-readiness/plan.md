# Plan：069-feishu-openai-integration-readiness

## 目标

把现有 Feishu ingress/outbound 与 `OpenAI-compatible` Brain provider 的 runtime 能力，补成仓库内可直接照抄的 env sample / getting-started 真值，并加 repo-local 文档约束测试。

## 实施边界

1. 先写失败测试，锁住 config sample 与 getting-started 中必须出现的 Feishu / provider 配置面。
2. 再补 `watchdog.env.example` 与 `getting-started.zh-CN.md`。
3. 最后更新 `ai_sdlc` 元数据并做对抗评审收口。

## 验证

- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
