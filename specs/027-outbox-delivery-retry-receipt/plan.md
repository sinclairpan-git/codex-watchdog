---
related_doc:
  - "docs/architecture/codex-watchdog-full-product-loop-design.md"
  - "specs/027-outbox-delivery-retry-receipt/spec.md"
  - "specs/026-canonical-action-approval-response-loop/spec.md"
---

# 实施计划：027-outbox-delivery-retry-receipt

## 目标

把 envelope 投递收成可靠 outbox / retry / receipt pipeline，让主动消息通知具备生产所需的最小可靠性。

## 架构摘要

- **Outbox before callback**：先持久化，再投递。
- **Delivery is not decision**：027 只负责怎么送，不负责怎么判。
- **Retryable by protocol**：不完整确认也按失败重试，而不是乐观视为 delivered。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Envelope Builder | `src/watchdog/services/delivery/envelopes.py` | 从 canonical decision / result records 构造 envelope |
| Outbox Store | `src/watchdog/services/delivery/store.py` | `decision_outbox` 保存待投递 envelope 真值，`delivery_outbox` 保存 attempt / retry / receipt，`outbox_seq` 提供稳定顺序 |
| Delivery Worker | `src/watchdog/services/delivery/worker.py` | 排序、回调、retry、receipt 校验 |
| Transport | `src/watchdog/services/delivery/http_client.py` | Feishu webhook HTTP 发送与响应解析 |
| 验证 | `tests/test_watchdog_delivery_worker.py`, `tests/test_watchdog_delivery_http.py` | 顺序、重试、receipt、失败升级 |

## 边界纪律

- `027` 只拥有 outbox / delivery / retry / receipt 语义。
- `027` 不拥有 policy、action execution 或 approval business logic。
- `027` 不拥有宿主渲染与飞书渠道语义。

## 分阶段计划

### Phase 1：冻结投递矩阵与 outbox 模型

- `decision_outbox` 只持有待投递 envelope 与稳定排序真值
- `delivery_outbox` 只持有 attempt / retry / receipt / failed 语义
- `outbox_seq`
- 决策结果到 envelope 的映射矩阵

### Phase 2：实现 delivery worker

- session 内稳定顺序
- 多 session 并行
- 回调协议解析

### Phase 3：实现 retry / receipt / failed semantics

- retryable failure
- delivered criteria
- 最大重试与失败升级

### Phase 4：测试与最小文档

- 投递顺序
- 去重
- backoff
- dead-letter / failure notes

## 测试计划

- `tests/test_watchdog_delivery_worker.py`
  - 决策结果投递矩阵
  - 顺序与并行
  - `outbox_seq`
- `tests/test_watchdog_delivery_http.py`
  - delivered criteria
  - retryable failure
  - receipt 校验
  - envelope 幂等

## 主要风险与应对

- 风险 1：delivery worker 偷偷补业务判断
  - 应对：只消费 canonical records
- 风险 2：2xx 但 body 不完整被误判 delivered
  - 应对：严格 delivered criteria
- 风险 3：重试打乱顺序
  - 应对：session 内顺序由 `fact_snapshot_version + outbox_seq` 锁住

## 验收口径

只有当以下条件同时满足，027 才算完成：

1. envelope 已通过持久 outbox 驱动，而不是内存直发；
2. delivered / retrying / failed 语义已落地；
3. 同 session 顺序稳定，多 session 可并行；
4. receipt 校验与 retry/backoff 已被测试锁住；
5. 本工作项仍未引入 policy 或 execution business logic。
