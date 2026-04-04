# 研究记录：M2 监管能力

## 决策

| 主题 | 结论 | PRD 依据 |
|------|------|----------|
| stuck 信号 | 首版以持久化字段 `last_progress_at`、`stuck_level` 与配置阈值为主；真实 transcript 来自后续 Codex 对接 | §5.2、§8.1 |
| steer | HTTP 注入到 A-Control-Agent；消息模板引用 PRD §8.4.1 | §9.3.3 |
| 循环失败 | 以 `last_error_signature` 字符串相等 + `failure_count` 递增为最小实现 | §5.4 |
| 审计 | 追加 JSONL，便于测试与 tail | §13.3 |

## 风险

- 与生产 Codex 事件字段对齐需在后续迭代校准；本工作项以可测规则与 API 为准。
