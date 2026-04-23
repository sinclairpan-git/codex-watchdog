---
related_doc:
  - "docs/architecture/codex-watchdog-full-product-loop-design.md"
  - "specs/028-webhook-response-api-reference-runtime/spec.md"
  - "specs/027-outbox-delivery-retry-receipt/spec.md"
---

# 实施计划：028-webhook-response-api-reference-runtime

## 目标

冻结 Watchdog 与 Feishu 之间的 webhook / response contract，并提供最小 reference runtime，证明宿主只做渠道适配。

## 架构摘要

- **Contract first**：先冻结 webhook / response contract，再给最小 reference runtime。
- **Reference, not kernel**：reference runtime 只能消费稳定 contract，不得引入第二套业务内核。
- **Host adapter only**：宿主只负责接收 envelope、渲染、接收输入、回传结构化响应。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract Docs | `docs/architecture/codex-watchdog-full-product-loop-design.md`, `docs/getting-started.zh-CN.md` | webhook / response contract 与宿主边界 |
| API Surface | `src/watchdog/api/feishu_callbacks.py`, `src/watchdog/api/feishu_responses.py` | 对 Feishu 暴露稳定接口 |
| Reference Runtime | `examples/codex_watchdog_client.py`, `examples/feishu_webhook_runtime.py` | 最小宿主模板 |
| 验证 | `tests/integration/test_feishu_integration_spine.py`, `tests/test_feishu_contracts.py` | 契约、shape、reference runtime |

## 边界纪律

- `028` 只拥有宿主接入 contract 与 reference runtime。
- `028` 不拥有 policy、execution、delivery retry 或运维告警。
- reference runtime 不得演化成第二个 Watchdog 内核。

## 分阶段计划

### Phase 1：冻结 webhook / response contract

- 请求头
- body shape
- receipt shape
- response shape

### Phase 2：接 API surface

- Feishu webhook callback ingress/egress
- response API shape

### Phase 3：补最小 reference runtime

- envelope 消费
- 消息映射
- 结构化回传

### Phase 4：文档与验证

- getting-started
- reference runtime 验证
- contract tests

## 测试计划

- `tests/test_feishu_contracts.py`
  - webhook headers/body
  - receipt shape
  - response request shape
- `tests/integration/test_feishu_integration_spine.py`
  - reference runtime 继续复用 stable route / stable contract

## 主要风险与应对

- 风险 1：reference runtime 膨胀成第二内核
  - 应对：只消费 envelope / response contract
- 风险 2：宿主自己重算决策
  - 应对：文档与测试禁止宿主承担策略语义

## 验收口径

只有当以下条件同时满足，028 才算完成：

1. Feishu 接入 contract 已冻结；
2. webhook / response API 已有稳定 shape 与鉴权边界；
3. reference runtime 可证明“宿主只做适配”；
4. 本工作项仍未引入第二套业务决策或状态机。
