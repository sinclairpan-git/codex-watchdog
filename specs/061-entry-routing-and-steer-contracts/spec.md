# Spec：061-entry-routing-and-steer-contracts

## 背景

`WI-060` 完成后，当前脏工作树中还剩下一条没有 formalize 的独立入口主题：

1. `FeishuAdapter.handle_message(...)` 允许直接消费自然语言 message
2. `command_routing.py` 支持 `native_thread_id -> canonical route/project_id` 的解析
3. `steer_template_registry()` 固定 runtime steer 模板与 reason code
4. `ActionCode` / `Effect` 新枚举为这些入口提供稳定 contract
5. adapter / integration tests 对 A-client stub 的签名对齐进行了显式约束

这条主题的重点不是新增业务决策，而是把“入口消息如何映射到稳定 command surface”以及“steer 模板/枚举是否保持一致”固定成正式 contract。

`WI-061` 因此只承担 Feishu entry routing and steer contracts 的 formal closeout。

## 范围

### In Scope

- `src/watchdog/services/adapters/feishu/adapter.py`
- `src/watchdog/services/adapters/feishu/intents.py`
- `src/watchdog/services/entrypoints/command_routing.py`
- `src/watchdog/services/action_executor/steer.py`
- `src/watchdog/contracts/session_spine/enums.py`
- `tests/test_watchdog_feishu_adapter.py`
- `tests/integration/test_feishu_integration_spine.py`
- `tests/test_watchdog_steer.py`

### Out of Scope

- 不重开 session command surface / restart preservation；
- 不重开 memory/risk/ops hardening；
- 不扩展新的产品动作域，只 formalize 已出现的入口/模板/枚举 contract。

## Formal Source

- `src/watchdog/services/adapters/feishu/adapter.py`
- `src/watchdog/services/adapters/feishu/intents.py`
- `src/watchdog/services/entrypoints/command_routing.py`
- `src/watchdog/services/action_executor/steer.py`
- `src/watchdog/contracts/session_spine/enums.py`
- `tests/test_watchdog_feishu_adapter.py`
- `tests/integration/test_feishu_integration_spine.py`
- `tests/test_watchdog_steer.py`

## 非 Owner 约束

- **FR-6101**：061 只关闭入口路由、steer 模板与枚举 contract，不新增决策逻辑。
- **FR-6102**：自然语言入口必须复用既有 canonical action/read surface，不得产生第二套入口协议。
- **FR-6103**：A-client fake/broken stub 必须和真实 client 的核心方法签名保持一致，避免测试假象通过。

## 功能需求

- **FR-6104**：自然语言消息必须能稳定映射到 canonical intent。
- **FR-6105**：`native_thread_id` 路由必须能在缺少 `project_id` 时解析到稳定 route。
- **FR-6106**：runtime steer 模板注册表必须为 soft/waiting_for_direction/break_loop/handoff_summary/severe_takeover 提供稳定 `reason_code + message`。
- **FR-6107**：新增 `ActionCode` / `Effect` 必须和入口路由保持一致。
- **FR-6108**：061 必须用 adapter/integration/steer 三组 targeted tests 覆盖上述 contract。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。061 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `specs/061-entry-routing-and-steer-contracts/spec.md`
   - `specs/061-entry-routing-and-steer-contracts/plan.md`
   - `specs/061-entry-routing-and-steer-contracts/tasks.md`
   - `specs/061-entry-routing-and-steer-contracts/task-execution-log.md`
   - `.ai-sdlc/work-items/061-entry-routing-and-steer-contracts/execution-plan.yaml`
   - `.ai-sdlc/work-items/061-entry-routing-and-steer-contracts/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
