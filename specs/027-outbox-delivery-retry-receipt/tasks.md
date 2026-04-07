# 任务分解：027-outbox-delivery-retry-receipt

> 对应规格：`specs/027-outbox-delivery-retry-receipt/spec.md`

## Task 27.1 冻结 envelope 投递矩阵与 outbox 边界

- **任务编号**：T271
- **状态**：已完成
- **目标**：把 `decision_outbox / delivery_outbox / outbox_seq` 与投递矩阵收敛成 formal boundary。
- **涉及文件**：
  - `docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md`
  - `specs/027-outbox-delivery-retry-receipt/spec.md`
  - `specs/027-outbox-delivery-retry-receipt/plan.md`
  - `specs/027-outbox-delivery-retry-receipt/tasks.md`
- **验证**：人工审阅 formal docs 是否与总设计 Section 4 / 5 的 WI-4 边界一致。

## Task 27.2 新增 envelope builder 与持久 outbox

- **任务编号**：T272
- **状态**：已完成
- **目标**：新增 envelope builder、outbox store 与 `outbox_seq`。
- **涉及文件**：
  - `src/watchdog/services/delivery/envelopes.py`
  - `src/watchdog/services/delivery/store.py`
  - `tests/test_watchdog_delivery_worker.py`
- **验证**：`uv run pytest -q tests/test_watchdog_delivery_worker.py`

## Task 27.3 新增 delivery worker、receipt 与 retry

- **任务编号**：T273
- **状态**：已完成
- **目标**：落回调发送、receipt 校验、重试与失败升级。
- **涉及文件**：
  - `src/watchdog/services/delivery/worker.py`
  - `src/watchdog/services/delivery/http_client.py`
  - `tests/test_watchdog_delivery_http.py`
- **验证**：`uv run pytest -q tests/test_watchdog_delivery_http.py`

## Task 27.4 锁住顺序语义与最小 operator notes

- **任务编号**：T274
- **状态**：已完成
- **目标**：锁住 session 内顺序与 dead-letter / failure notes。
- **涉及文件**：
  - `src/watchdog/services/delivery/worker.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
- **验证**：`uv run pytest -q tests/test_watchdog_delivery_worker.py tests/test_watchdog_delivery_http.py`

## 整体验收

- `027` 是完整产品闭环中的 `WI-4`，只负责 outbox / delivery / retry / receipt。
- `027` 完成后，OpenClaw 可稳定接收主动 envelope，不依赖内存直发。
- `027` 不重跑 policy，不承担 action / approval business logic。
