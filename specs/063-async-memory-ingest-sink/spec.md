# Spec：063-async-memory-ingest-sink

## 背景

`WI-062` 已经补齐 `provider runtime + durable memory + resident capsule`，但对抗评审留下一个残余
P1：`SessionService.record_event()` 仍同步调用 `MemoryHubService.ingest_session_event()`。这意味着
长期记忆沉淀仍在真相写入热路径上，违背了“先写真相，再异步沉淀”的原始边界。

`WI-063` 的目标不是重写 `Memory Hub`，而是把 `Session Service -> Memory Hub` 收敛为真正的
durable enqueue + async worker drain，让 Session 真相与长期记忆沉淀解耦。

## 范围

### In Scope

- `src/watchdog/services/memory_hub/ingest_queue.py`
- `src/watchdog/services/memory_hub/ingest_worker.py`
- `src/watchdog/services/memory_hub/__init__.py`
- `src/watchdog/main.py`
- `src/watchdog/settings.py`
- `tests/test_watchdog_memory_hub.py`

### Out of Scope

- 不改写 `MemoryHubService` 的 advisory contract；
- 不引入新的外部消息中间件；
- 不在本工单内扩展失败重试策略与监控 API；
- 不改变 `Session Service` 作为真相写屏障的 owner 身份。

## Formal Source

- `docs/architecture/codex-long-running-autonomy-design.md`
- `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
- `specs/062-global-design-provider-memory-closure/spec.md`
- `src/watchdog/services/session_service/service.py`
- `src/watchdog/services/memory_hub/service.py`
- `src/watchdog/main.py`

## 非 Owner 约束

- **FR-6301**：`Session Service` 仍是唯一真相写入屏障；Memory 侧只能消费已落盘事件。
- **FR-6302**：`record_event()` 成功与否不得取决于 `MemoryHub` 摄取是否成功。
- **FR-6303**：内存队列不可接受；至少要有 durable queue file，进程重启后仍可继续 drain。
- **FR-6304**：Resident / archive 的可见性必须发生在 worker drain 之后，而不是 session write 当下。

## 功能需求

- **FR-6305**：应用必须把 session event listener 从直接 `ingest_session_event()` 改为 `enqueue_event()`。
- **FR-6306**：队列记录必须至少保留 `event_id / project_id / session_id / event_type / event_payload / status / attempts`。
- **FR-6307**：worker 必须能够 claim pending record、调用 `MemoryHubService.ingest_session_event()`、并回写 `processed` 或 `failed`。
- **FR-6308**：进程启动时必须恢复中断在 `processing` 的记录，避免队列永久卡死。
- **FR-6309**：targeted tests 必须证明：
  - event 写入后只会先入队；
  - drain 前 `resident_capsule` / archive refs 不可见；
  - drain 后 MemoryHub 可见；
  - ingest 失败不会回滚 Session 真相，且队列状态可观测。

## Docs baseline hash recipe

`docs_baseline_ref` 生成方式沿用现有 work item 规则，artifact set 固定为：

- `specs/063-async-memory-ingest-sink/spec.md`
- `specs/063-async-memory-ingest-sink/plan.md`
- `specs/063-async-memory-ingest-sink/tasks.md`
- `specs/063-async-memory-ingest-sink/task-execution-log.md`
- `.ai-sdlc/work-items/063-async-memory-ingest-sink/execution-plan.yaml`
- `.ai-sdlc/work-items/063-async-memory-ingest-sink/latest-summary.md`
