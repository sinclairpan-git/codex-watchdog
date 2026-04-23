# Spec：060-memory-advisory-fail-closed-and-ops-hardening

## 背景

`WI-059` 完成后，当前脏工作树中仍有一批尚未 formalize 的改动，但它们已经不再属于 session command surface / restart preservation。

剩余改动集中在另一条独立 hardening 主题：

1. `Brain` 与 recovery hot path 开始消费 `Memory Hub` runtime advisory context
2. `Memory Hub` 对 goal conflict / outage 形成 fail-closed degradation 信号
3. `CodexAppServerBridge` 与 risk classifier 对 workspace 外、网络、凭证等高风险边界进入 human gate
4. approvals proxy、healthz 与 metrics 进一步把 fail-closed 和 release gate blocker 暴露为稳定观测面

这条主题的共同目标不是新增产品功能，而是保证：

- runtime advisory 只能作为参考输入，不能覆盖 `SessionService/GoalContract` 真值；
- memory conflict / unavailable 时必须留下 canonical degradation event；
- 高风险 permission boundary 必须 fail closed；
- ops healthz / metrics 必须反映 release gate blocker、task/approval/recovery 总量。

`WI-060` 因此只承担 memory advisory / fail-closed / ops hardening 这条能力链的 formal closeout。

## 范围

### In Scope

- `MemoryHubService.build_runtime_advisory_context(...)`
- `BrainDecisionService` 对 memory advisory 的消费与 conflict degradation 记录
- recovery hot path 对 memory advisory 的消费与 unavailable degradation 记录
- risk classifier 与 `CodexAppServerBridge` 的 fail-closed permission boundary
- approvals proxy 的 fail-closed client path
- watchdog / a-control-agent healthz 与 metrics 的 hardening
- 对应 targeted tests、formal docs 与 `.ai-sdlc` 状态。

### Out of Scope

- 不新增新的业务动作或 session command surface；
- 不重写 `Brain` 的主决策意图体系；
- 不把 observability 扩展成独立新平台能力；
- 不回改 `WI-059` 已关闭的 command/restart 边界。

## Formal Source

- `src/watchdog/services/brain/service.py`
- `src/watchdog/services/memory_hub/service.py`
- `src/watchdog/services/session_spine/recovery.py`
- `src/a_control_agent/risk/classifier.py`
- `src/watchdog/api/approvals_proxy.py`
- `src/watchdog/api/ops.py`
- `src/watchdog/observability/metrics_export.py`
- `src/a_control_agent/observability/metrics_export.py`
- `src/watchdog/main.py`
- `src/a_control_agent/main.py`
- `tests/test_watchdog_memory_hub.py`
- `tests/test_watchdog_memory_degradation.py`
- `tests/test_codex_app_server_bridge.py`
- `tests/test_watchdog_ops.py`

## 非 Owner 约束

- **FR-6001**：060 只做 runtime advisory / fail-closed / ops hardening，不新增产品语义。
- **FR-6002**：memory advisory 只能作为辅助上下文，不能覆盖 `SessionService` / `GoalContract` 的当前真值。
- **FR-6003**：workspace 外、网络、凭证、发布等高风险边界必须保持 fail closed，不得自动放行。
- **FR-6004**：ops healthz / metrics 只能暴露既有 canonical truth，不得发明第二套状态来源。

## 功能需求

- **FR-6005**：`MemoryHubService.build_runtime_advisory_context(...)` 必须产出 packet refs、skills、precedence，并在 goal conflict 时明确 `memory_conflict_detected` degradation。
- **FR-6006**：`BrainDecisionService` 与 recovery hot path 消费 memory advisory 时，必须在 conflict / unavailable 时记录 canonical degradation event，但不得改变原本的 intent / recovery 结论。
- **FR-6007**：risk classifier 与 bridge 必须对 fail-closed permission boundary 进入 human gate。
- **FR-6008**：approvals proxy 必须使用一致的 fail-closed HTTP client 路径。
- **FR-6009**：healthz / metrics 必须正确暴露：
  1. release gate blockers
  2. task totals
  3. pending approval totals
  4. completed recovery receipt totals
- **FR-6010**：060 必须用 targeted tests 覆盖上述 memory/risk/ops hardening contract。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。060 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `specs/060-memory-advisory-fail-closed-and-ops-hardening/spec.md`
   - `specs/060-memory-advisory-fail-closed-and-ops-hardening/plan.md`
   - `specs/060-memory-advisory-fail-closed-and-ops-hardening/tasks.md`
   - `specs/060-memory-advisory-fail-closed-and-ops-hardening/task-execution-log.md`
   - `.ai-sdlc/work-items/060-memory-advisory-fail-closed-and-ops-hardening/execution-plan.yaml`
   - `.ai-sdlc/work-items/060-memory-advisory-fail-closed-and-ops-hardening/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
