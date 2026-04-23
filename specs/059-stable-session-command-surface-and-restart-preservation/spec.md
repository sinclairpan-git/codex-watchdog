# Spec：059-stable-session-command-surface-and-restart-preservation

## 背景

`WI-058` 完成后，repo-local formal truth 已明确当前不存在 residual blocker，且 `WI-059` 不再被保留为 long-running plan truth sync 候选。

但当前工作树中存在一批尚未 formalize 的高耦合脏改动，它们集中指向同一条能力链：

1. `session_spine` 新增稳定动作面：`pause`、`resume`、`summarize`、`force_handoff`、`retry_with_conservative_path`
2. task lifecycle 新增 canonical `status/phase` 归一化与动作转移校验
3. Feishu / Feishu 新增 natural-language -> canonical intent 路由
4. Codex runtime service 新增 `pause` control endpoint
5. Watchdog restart 后，稳定读面需要保留 pending approvals 与 action receipts，不得因为重启而丢失已存在真值

这批改动涉及同一条 control/read surface contract：外部入口如何映射到 canonical action、动作何时允许、A side 如何承接 pause/handoff/resume、以及重启后读面如何维持既有真值。

`WI-059` 因此只承担 stable session command surface and restart preservation：为这条能力链建立正式 owner 边界、测试闭环与 repo-side closeout。

## 范围

### In Scope

- `session_spine` 稳定动作面新增：
  - `pause_session`
  - `resume_session`
  - `summarize_session`
  - `force_handoff`
  - `retry_with_conservative_path`
- action alias route、intent 映射与 canonical handler 复用；
- task `status/phase` 归一化与动作转移 fail-closed 校验；
- Codex runtime service 的 `pause` control endpoint；
- Feishu/Feishu 的 command request / natural-language 路由到 canonical read/write surface；
- restart 后 pending approvals 与 action receipts 的稳定保留与可读性验证；
- 对应 targeted tests、formal docs 与 `.ai-sdlc` 状态。

### Out of Scope

- 不重新设计 `Brain`、`Goal Contract`、`Memory Hub` 的既有 owner 语义；
- 不扩展新的产品域动作类型；
- 不重写 long-running implementation plan；
- 不修改 `WI-035`、`WI-048`、`WI-049`、`WI-050` 的已关闭 owner 边界，只消费它们冻结下来的 canonical surface。

## Formal Source

- `src/watchdog/api/session_spine_actions.py`
- `src/watchdog/services/session_spine/actions.py`
- `src/watchdog/services/session_spine/task_state.py`
- `src/watchdog/services/adapters/feishu/intents.py`
- `src/watchdog/services/adapters/feishu/adapter.py`
- `src/watchdog/services/feishu_control/service.py`
- `src/a_control_agent/api/recovery.py`
- `tests/test_watchdog_session_spine_api.py`
- `tests/test_watchdog_feishu_control.py`
- `tests/test_watchdog_action_execution.py`
- `tests/test_a_control_agent.py`

## 非 Owner 约束

- **FR-5901**：059 只关闭 stable command surface / restart preservation 这条能力链，不新增不相干 runtime 功能。
- **FR-5902**：059 只能复用既有 canonical action / approval / receipt / session projection contract，不得发明第二套读写面。
- **FR-5903**：059 对动作转移必须 fail closed；任何不在允许状态集内的 command surface 都必须返回稳定拒绝语义。
- **FR-5904**：059 不得让 restart 后的 stable read surfaces 重新执行动作，只允许读取已持久化真值。

## 功能需求

- **FR-5905**：canonical action surface 必须支持 `pause_session`、`resume_session`、`summarize_session`、`force_handoff`、`retry_with_conservative_path`，且 alias route 必须复用同一 canonical handler。
- **FR-5906**：task lifecycle 必须把 legacy `status/phase` 归一化到稳定 canonical surface，并通过统一 helper 校验动作是否允许发生。
- **FR-5907**：Feishu/Feishu command request 必须能把自然语言命令解析到 canonical intent，并复用同一 read/write surface。
- **FR-5908**：Codex runtime service 必须暴露 `pause` endpoint，并对 task store / event log / audit log 写入稳定结果。
- **FR-5909**：restart 后 stable read surfaces 必须继续保留并返回：
  1. pending approvals
  2. 已存在 action receipts
  3. 不得因重启而触发动作重放
- **FR-5910**：059 必须用 targeted tests 覆盖上述 command surface、restart preservation 与路由 contract。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。059 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `specs/059-stable-session-command-surface-and-restart-preservation/spec.md`
   - `specs/059-stable-session-command-surface-and-restart-preservation/plan.md`
   - `specs/059-stable-session-command-surface-and-restart-preservation/tasks.md`
   - `specs/059-stable-session-command-surface-and-restart-preservation/task-execution-log.md`
   - `.ai-sdlc/work-items/059-stable-session-command-surface-and-restart-preservation/execution-plan.yaml`
   - `.ai-sdlc/work-items/059-stable-session-command-surface-and-restart-preservation/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
