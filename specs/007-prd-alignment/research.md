---
related_doc:
  - "codex-watchdog-prd.md"
---

# 研究记录：007-prd-alignment

## 本工作项仍不编码的已知偏差（登记备查）

| 偏差 | 说明 | 归属 |
|------|------|------|
| 真实 Codex transcript / turn 事件 | 需 app-server 协议与长期联调 | 后续对接工作项 |
| 飞书 L2/L3 提醒与人工闭环 | PRD §3.2 Out of Scope | 宿主 Feishu / 渠道 |
| `GET .../events` SSE | 可选 API，非 M1–M5 必交 | 后续 |
| 指标「卡顿次数」独立计数 | 当前以 steer/审计代理；可再加专用 counter | 可选增强 |
| P95 / 分布式 tracing | 未在本仓库实现 | 运维层 |

## 本工作项内编码的偏差收口

见 `spec.md` FR-501–FR-504。
