# 2026-04-10 运行环境清理与 `unknown-decision` 问题归档

## 本次处理范围

- 先停止当前机器上所有 OpenClaw 相关常驻运行态。
- 只做事实梳理、证据归档、根因分析。
- 本文档不包含业务逻辑修复，也不把分析伪装成“已经修好”。

## 已完成的环境清理

2026-04-10 已将以下 `launchd` 服务从当前用户会话中 `bootout`：

- `com.openclaw.a-control-agent`
- `com.openclaw.a-control-agent.public-tunnel`
- `com.openclaw.watchdog`
- `com.openclaw.watchdog.public-tunnel`
- `com.openclaw.watchdog.endpoint-notifier`

清理后复查结果：

- `launchctl list` 中已无任何 `com.openclaw.*` 常驻项。
- 端口 `8710` 与 `8720` 已无监听。
- 当前机器上不存在会自动继续投递消息的 OpenClaw runtime 进程。

说明：

- 这里只是把运行态卸掉，`~/Library/LaunchAgents/*.plist` 文件仍保留在磁盘上，后续若要恢复，需要显式 `bootstrap`。
- 这样做的目的，是先把“持续制造新噪声的系统”停住，再分析根因。

## 问题现象

用户在飞书侧持续收到大量自动通知，表现为：

- 决策名显示为 `unknown-decision`
- 动作名显示为 `unknown-action`
- 同一项目在短时间内重复收到大量类似消息

该现象说明至少存在两个层面的问题：

1. 上游系统仍在持续生成并投递 envelope。
2. 下游 OpenClaw/飞书渲染链路没有正确识别当前 envelope 类型，回退成了 `unknown-*`。

## 已确认事实

### 1. 当前不是“一套开发环境”，而是“仓库目录 + 外部 runtime 目录”混跑

当前活跃链路来自两套目录：

- 当前仓库：`/Users/sinclairpan/project/openclaw-codex-watchdog`
- 外部 runtime：`/Users/sinclairpan/openclaw-codex-watchdog-a-runtime`

关键证据：

- `~/Library/LaunchAgents/com.openclaw.watchdog.plist`
  - 从当前仓库启动 `scripts/start_watchdog.sh`
- `~/Library/LaunchAgents/com.openclaw.watchdog.endpoint-notifier.plist`
  - 从外部 runtime 目录启动 `scripts/start_watchdog_endpoint_notifier.sh`
- `~/Library/LaunchAgents/com.openclaw.a-control-agent.public-tunnel.plist`
  - 从外部 runtime 目录启动 tunnel
- `~/Library/LaunchAgents/com.openclaw.watchdog.public-tunnel.plist`
  - 从外部 runtime 目录启动 tunnel
- `bin/start-a-agent.sh`
  - 从当前仓库启动 A agent，但读取当前仓库根目录下的 `.env.a`

结论：

- 服务启动入口并不统一。
- 数据、配置、tunnel、notifier 被拆在两处目录中。
- 这和“只用一套开发环境”的目标相违背。

### 2. 配置文件显式把状态写到外部 runtime 数据目录

当前本地环境文件中存在明显分裂：

- `.env.a`
  - `A_AGENT_DATA_DIR=/Users/sinclairpan/openclaw-codex-watchdog-a-runtime/.data/a_control_agent`
- `.env.w`
  - `WATCHDOG_DATA_DIR=/Users/sinclairpan/openclaw-codex-watchdog-a-runtime/.data/watchdog`
  - `WATCHDOG_OPENCLAW_WEBHOOK_ENDPOINT_STATE_FILE=/Users/sinclairpan/openclaw-codex-watchdog-a-runtime/.data/watchdog/openclaw_webhook_endpoint.json`
  - `WATCHDOG_PUBLIC_URL_STATE_FILE=/Users/sinclairpan/openclaw-codex-watchdog-a-runtime/.data/watchdog/public_endpoint_state.json`

而代码默认值本身并不是这样：

- `src/watchdog/settings.py`
  - `data_dir` 默认是 `.data/watchdog`
  - `openclaw_webhook_base_url` 默认是 `http://127.0.0.1:8740`

结论：

- 仓库代码默认倾向本地单目录开发。
- 当前实际运行配置强行把核心状态切到了外部 runtime 目录。
- 这导致“代码看的是一份状态，实际运行又写另一份状态”。

### 3. 当前仓库本地 `.data` 基本空，真正活跃的是外部 runtime outbox

本地仓库 `.data/watchdog` 中：

- `delivery_outbox.json` 基本为空
- `policy_decisions.json` 基本为空
- `canonical_approvals.json` 基本为空

外部 runtime `.data/watchdog` 中：

- `delivery_outbox.json`
  - `next_outbox_seq: 3684`
  - `delivery_outbox` 共 3683 条
  - `decision_outbox` 共 3406 条
- `openclaw_webhook_endpoint.json`
  - 当前 endpoint 为一个 `trycloudflare` 地址
- `public_endpoint_state.json`
  - 当前 watchdog 公网地址也是另一个 `trycloudflare` 地址

结论：

- 真正持续投递消息的是外部 runtime 状态，不是当前仓库内的 `.data`。
- 如果只盯当前仓库 `.data`，会误判成“系统没在发消息”。

### 4. runtime 日志里同时存在 outbox 损坏、notifier 连接失败、tunnel 抖动

已确认的日志证据：

- `~/Library/Logs/openclaw-watchdog.err.log`
  - 多次出现 `delivery_outbox.json` JSON 解析失败
  - 典型报错：`Invalid JSON: trailing characters`
  - 说明 outbox 文件曾经被写坏，后台编排和 delivery worker 都受影响
- `~/Library/Logs/openclaw-watchdog-endpoint-notifier.err.log`
  - 多次出现 `httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known`
  - 说明 notifier 回调 bootstrap webhook 时存在目标不可解析或不可达
- `~/Library/Logs/openclaw-watchdog.public-tunnel.err.log`
  - 多次出现 quick tunnel 超时与重连
  - 说明公网地址本身不稳定

结论：

- 当前系统不仅环境混跑，而且传输层本身也在抖动。
- 这些问题会放大噪声、制造重复投递和状态错觉。

## `unknown-decision` 的直接原因

### 1. 仓库实际发出的并不是字面上的 `unknown-decision`

对外部 runtime `delivery_outbox.json` 中 `project_id=ai_sdlc` 的记录做抽样统计后，最常见的 envelope 组合是：

- `decision` + `auto_execute_and_notify` + `continue_session`
- `notification` + `decision_result` + `auto_execute_and_notify` + `continue_session`
- `notification` + `progress_summary` + `decision_result=None` + `action_name=None`

这里的关键信号是第三类：

- `notification_kind=progress_summary`
- `decision_result` 为空
- `action_name` 为空

这和截图中的“unknown-decision / unknown-action”高度吻合。

### 2. 代码中 `progress_summary` 本来就不应该被按“决策通知”渲染

`src/watchdog/services/delivery/envelopes.py` 中：

- `build_progress_summary_envelope(...)`
  - 明确构造 `notification_kind="progress_summary"`
  - 同时把 `decision_result=None`
  - 同时把 `action_name=None`

这表示：

- `progress_summary` 是独立的“进展摘要通知”
- 它不是 `decision_result` 类型通知
- 它天然不带动作名和决策结果

因此，只要下游把它错误地当成“自动决策通知”来渲染，就一定会回退成：

- `unknown-decision`
- `unknown-action`

### 3. 当前最合理的根因判断

在未直接拿到 OpenClaw/飞书渲染代码的前提下，基于现有证据，当前最合理的结论是：

- Watchdog 上游持续发送了大量 `progress_summary` 通知。
- OpenClaw/飞书下游没有先按 `envelope_type + notification_kind` 分流。
- 下游直接把所有 `notification` 都按“决策结果通知模板”渲染。
- 当 `decision_result` / `action_name` 缺失时，就落到了 `unknown-*` 默认值。

这是一条基于证据的推断，不是对下游代码的直接验证；但它已经足够解释当前截图现象，并且与 outbox 实际数据完全一致。

## 为什么会“一晚上又多一百多条”

`unknown-*` 刷屏不是单点错误，而是多因素叠加：

### 1. resident orchestrator 持续运行

`src/watchdog/main.py` 的 `create_runtime_app()` 会启用后台循环，包括：

- resident orchestrator
- delivery worker
- session refresh loop

只要这个 runtime 常驻，它就会持续评估、持续入队、持续尝试投递。

### 2. `progress_summary` 会在条件满足时主动发送

`src/watchdog/services/session_spine/orchestrator.py` 的 `_maybe_emit_progress_summary()` 会在：

- 指纹变化
- 节流间隔满足

时主动生成 progress summary。

所以即使没有新的人工操作，只要系统认为“会话状态发生变化”，就可能继续产生通知。

### 3. tunnel/notifier 不稳定会放大噪声

当公网地址变化、notifier 回调失败、endpoint state 反复更新时：

- delivery 会不断面对新的目标地址
- transport failure 可能触发 requeue
- 操作人员看到的效果就是“消息停不下来”

### 4. outbox 文件曾损坏，增加了排障混乱度

`delivery_outbox.json` 发生过 JSON 尾部损坏，这意味着：

- 某些时刻后台 worker 根本无法正常读取状态
- 错误恢复与重试行为可能不一致
- 日志中的“异常”和飞书侧的“重复消息”会混在一起，让问题看上去像是随机抖动

这更像是次生稳定性问题，而不是 `unknown-decision` 这个文案现象的第一根因。

## 根因分层

### 第一根因

运行体系被拆成了“当前仓库 + 外部 runtime + 多个 launchd + 双 quick tunnel + notifier”的混合形态，导致：

- 配置源不唯一
- 数据目录不唯一
- 真实活跃状态不在当前仓库
- 系统持续自驱动地产生并投递 envelope

### 第二根因

下游 OpenClaw/飞书渲染链路没有正确区分：

- `decision_result`
- `progress_summary`
- 其他 notification 类型

最终把 `progress_summary` 渲染成了 `unknown-decision` / `unknown-action`。

### 次生问题

- `delivery_outbox.json` 写入可靠性不足，曾出现 JSON 损坏。
- quick tunnel 与 bootstrap notifier 稳定性不足。
- 这些问题会扩大重复投递与观测噪声，但不是截图文案的最直接来源。

## 当前结论

截至 2026-04-10，本问题可以归纳为：

1. 当前机器长期运行着一套不受控的常驻 runtime，而不是单一开发环境。
2. 真正发消息的状态落在外部 runtime 数据目录，不在当前仓库 `.data`。
3. Watchdog 的 `progress_summary` 被下游当成“自动决策通知”渲染，因字段缺失回退成 `unknown-*`。
4. tunnel/notifier/outbox 损坏让重复消息、失败重试、状态漂移进一步放大。

## 在再次动代码之前，建议遵循的顺序

1. 保持当前 `launchd` 运行态关闭，不要再让旧 runtime 自动恢复。
2. 先统一环境基线：
   - 只保留一个工作目录
   - 只保留一套 `.data`
   - 取消 `.env.a` / `.env.w` 指向外部 runtime 目录的做法
3. 先修协议与渲染契约：
   - 下游必须先按 `envelope_type`
   - 对 `notification` 还要继续按 `notification_kind`
   - `progress_summary` 不允许走 `decision_result` 模板
4. 再修投递稳定性：
   - `delivery_outbox.json` 的原子写入/锁保护
   - tunnel/notifier 的失败观测与降噪
5. 最后再恢复常驻运行，并且只能从单一开发环境恢复。

## 本次归档的边界

本文已经能解释“为什么会持续刷 `unknown-decision`”，也已经明确指出“不是继续盲改代码的时候”。

但以下事项仍未在当前仓库内直接验证：

- OpenClaw/飞书渲染代码的具体 fallback 分支
- 外部 runtime 目录中的全部本地脚本差异
- `delivery_outbox.json` 曾损坏时的具体写入竞争路径

这些应在下一轮修复中，按本文给出的顺序逐项验证，而不是重新把 runtime 拉起后继续试错。
