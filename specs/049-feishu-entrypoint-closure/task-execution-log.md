# 执行日志：049-feishu-entrypoint-closure

## 2026-04-16

### Phase 1：scope recovery / formal docs freeze

- 基于 `WI-047` 生成的 `matrix-owner-ledger.yaml`，已把 owner=`WI-049` 的 92 条矩阵行收敛为当前 work item 的固定边界。
- 当前收紧后的 049 边界：
  - 只做 Feishu 主入口、Feishu compatibility 入口与自然语言到 canonical route 的收口；
  - 不重定义 `WI-048` 已冻结的 runtime semantics / action surface / fail-closed boundary；
  - 不进入 `WI-050` 的性能 / 重启 / 安全 / 可靠性 / 交付物验收；
  - 不进入 `WI-051` 的高耦合 test hardening。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/049-*` 基线。
- 当前 canonical branch 已切到 `codex/049-feishu-entrypoint-closure`。
- 当前下一执行入口切换为 `T492`：先写失败测试锁定 Feishu / Feishu / natural-language entry contract，再进入实现。

### Phase 2：red tests freeze Feishu / Feishu entry contract

- 先补两条最小红测，锁定入口层必须消费正式 canonical route：
  - `tests/test_watchdog_feishu_control.py::test_feishu_control_command_request_routes_progress_query_to_canonical_reply`
  - `tests/test_watchdog_feishu_adapter.py::test_adapter_routes_natural_language_progress_message_to_canonical_reply`
- 首轮红测结果：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_feishu_adapter.py`
  - 结果：`2 failed, 21 passed`
  - 失败原因固定为：
    - Feishu `command_request` 尚未接到 canonical query/action route；
    - `FeishuAdapter` 尚不支持 natural-language `handle_message(...)` contract。
- 第二轮继续补充控制动作与线程路由红测，冻结 049 的剩余 contract：
  - Feishu `暂停` 命令必须返回 canonical `pause_session` 回执，并把 receipt 落到 `ActionReceiptStore`；
  - Feishu / Feishu 必须支持 `native_thread_id -> project_id` 路由；
  - Feishu compatibility 入口对外仍暴露自然语言 `get_session` 语义，不泄漏内部 `get_session_by_native_thread` 路由细节。
- 扩展红测结果：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py`
  - 结果：`4 failed, 43 passed`
  - 失败点固定为 `native_thread_id` 未接入入口层与 `pause` receipt/assertion 缺口。

### Phase 3：Feishu primary command gateway 与 shared intent mapping

- 已在 `src/watchdog/services/feishu_control/service.py` 为 `command_request` 补齐正式消费路径：
  - 新增 `command_text` / `native_thread_id` contract；
  - 强制 `dm` 渠道；
  - 要求 `project_id` 或 `native_thread_id` 至少提供一个；
  - 统一生成 `feishu:{client_request_id}` 形式的 idempotency key。
- 已把自然语言入口解析收口到共享 helper：
  - 新增 `src/watchdog/services/entrypoints/command_routing.py`
  - 固定 `message -> intent -> project/native_thread route` 的共享逻辑；
  - 不再让 Feishu 和 Feishu 各自维护一套 project/native-thread 解析分支。
- `tests/test_watchdog_feishu_control.py` 已覆盖：
  - 进展查询；
  - `暂停` 动作；
  - `native_thread_id` 路由；
  - canonical receipt 落盘。

### Phase 4：Feishu compatibility route 收口

- `src/watchdog/services/adapters/feishu/adapter.py` 已新增/收口：
  - `handle_message(...)` 自然语言入口；
  - 共享 helper 驱动的 `native_thread_id` 路由；
  - 只在内部使用 `get_session_by_native_thread`，对外仍返回用户请求的 `get_session` 语义；
  - 写动作默认 idempotency key 继续可重放且稳定。
- `src/watchdog/services/adapters/feishu/intents.py` 已作为共享 intent catalog 使用，Feishu 与 Feishu 均复用同一套短指令映射。
- 集成验证结果：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py`
  - 结果：`47 passed in 0.79s`
- 当前 `WI-049` 的正式入口闭环已具备以下证据：
  - Feishu primary entry 可直接查询/控制 canonical route；
  - Feishu compatibility entry 不再维护独立自然语言语义；
  - `native_thread_id` / `project_id` 路由统一；
  - 入口动作继续复用 canonical receipt discipline。
