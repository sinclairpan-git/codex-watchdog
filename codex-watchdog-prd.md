# Feishu 自建机器人 × Codex 双机会话监管系统开发需求文档（PRD + Technical Spec）

- 文档名称：Feishu 自建机器人 × Codex 双机会话监管系统
- 版本：V1.0
- 日期：2026-04-03
- 状态：可直接进入 Codex / Cursor 开发
- 适用范围：
  - runtime 机器：运行 Codex、Codex app-server、被开发仓库、Codex runtime service
  - watchdog 机器：运行 Feishu 自建机器人、Watchdog/Policy Engine
  - 消息入口：飞书
- 已知前提：
  - Feishu 自建机器人 ↔ 飞书通路已存在
  - 本项目不负责飞书机器人接入与 Feishu 自建机器人 渠道打通
  - 本项目从 Feishu 自建机器人 已接收到飞书消息之后开始

---

## 1. 项目背景

用户当前使用方式为：
- runtime 机器使用 Codex 执行长期开发任务
- watchdog 机器运行 Feishu 自建机器人，作为统一的外部交互与监管入口
- 已经具备 Feishu 自建机器人 ↔ 飞书消息通路

当前痛点：
1. 无法在飞书中随时询问 runtime 机器当前开发任务进展
2. Codex 长任务在出现卡顿、等待下一步、上下文压力过高、循环失败时，缺少自动处理机制
3. 当需要权限审批时，无法按风险等级自动处理或精准提醒人工处理
4. 缺少 A/B 双机之间的标准化通信协议与可恢复的任务线程管理能力

因此需要建设一套“双机会话监管系统”，让 watchdog 机器上的 Feishu 自建机器人 能够通过结构化接口监管 runtime 机器上的 Codex 开发会话，并在飞书中提供问答、自动处理、授权分级和异常恢复能力。

---

## 2. 项目目标

### 2.1 总体目标

在不依赖桌面 UI 监控的前提下，基于 Codex 的协议层能力实现：
- 任务进展可查询
- 任务状态可监管
- 卡顿/等待/上下文压力可自动处理
- 授权审批可分级自动化
- 线程可恢复、可续话、可追踪

### 2.2 成功标准

系统上线后，应满足以下成功标准：

1. 用户可在飞书中随时查询指定项目任务进展，响应时间小于 5 秒
2. 对于“无进展卡顿”，系统可在设定阈值后自动触发一次 steer 并记录动作
3. 对于“等待下一步指示”，系统可在任务目标明确时自动选择保守路径继续执行
4. 对于“上下文压力高/线程退化”，系统可自动生成 handoff summary，并执行 resume 或新线程续跑
5. 对于授权请求，可按 L0/L1/L2/L3 四级风险模型处理，其中 L0/L1 可自动处理，L2/L3 可在飞书中精确提醒人工决策
6. 关键状态、审批、自动处理动作均具备可审计日志

---

## 3. 项目范围

### 3.1 In Scope

本项目包括：
1. runtime 机器的 Codex runtime service 服务开发
2. watchdog 机器的 Watchdog / Policy Engine 服务开发
3. A/B 间的内网通信协议与鉴权机制
4. 项目任务、线程、审批、状态、日志的数据模型
5. Feishu 自建机器人 调用 Watchdog 的集成接口
6. 自动卡顿处理、自动 steer、自动 handoff / resume 逻辑
7. 授权风险等级判断与自动/人工审批流程
8. 查询进展、查看最近改动、查看阻塞点等飞书侧能力
9. 全链路 observability（日志、事件、审计）

### 3.2 Out of Scope

本项目不包括：
1. 飞书机器人、Feishu 自建机器人 渠道插件本身的安装与接入
2. runtime 机器桌面 UI 层级的视觉监控或自动点击
3. 完全无人值守地自动批准所有高风险命令
4. git push / release / 发布流程自动化
5. 远程桌面控制、通用 SSH 运维入口
6. 对 Feishu 自建机器人 核心代码进行深度侵入式修改（优先通过外置服务集成）

---

## 4. 总体方案

### 4.1 架构原则

1. A 负责执行，B 负责监管
2. B 不直接控制 A 的桌面 UI
3. B 不直接调用 Codex 原始底层协议，而通过 Codex runtime service 获取业务化接口
4. 关键状态必须结构化，不依赖自然语言猜测
5. 审批必须分级，不允许默认全自动放行高风险操作
6. 所有自动处理动作必须可审计、可回放

### 4.2 总体架构图

```text
飞书
  ↓
Feishu 自建机器人 (B)
  ↓
Watchdog / Policy Engine (B)
  ↓  HTTPS / WebSocket / 内网 RPC（推荐 HTTPS + Token）
Codex runtime service (A)
  ↓
Codex app-server (A)
  ↓
Repo / Workspace / Tests (A)
```

### 4.3 组件职责

#### runtime 机器组件

##### 4.3.1 Codex app-server
职责：
- 作为 Codex 协议层入口
- 提供线程、历史、审批、事件流能力
- 为 Codex runtime service 提供底层会话接口

##### 4.3.2 Codex runtime service
职责：
- 对上提供标准化任务接口
- 对下封装 Codex app-server 能力
- 保存 project_id ↔ thread_id 映射
- 汇总任务状态、线程状态、上下文压力、审批请求
- 执行 steer、resume、handoff 等动作
- 采集工作目录变更、测试结果、错误信号

##### 4.3.3 Repo Watcher（可内嵌到 Codex runtime service）
职责：
- 监听文件修改
- 统计最近一段时间是否存在有效变更
- 辅助判断“真卡顿”与“长测试执行中”

#### watchdog 机器组件

##### 4.3.4 Feishu 自建机器人
职责：
- 接收飞书消息
- 调用 Watchdog 接口
- 将结构化状态转化为自然语言返回飞书
- 接收人工审批决策并转发给 Watchdog

##### 4.3.5 Watchdog / Policy Engine
职责：
- 定时轮询 Codex runtime service 获取状态
- 判断卡顿、等待、循环失败、上下文压力
- 决定是否自动 steer、是否通知用户
- 对审批请求做风险分级
- 为 Feishu 自建机器人 提供统一业务接口

---

## 5. 关键业务场景

### 5.1 场景一：飞书随时查询任务进展

用户在飞书中发送：
- “现在进展”
- “ai-sdlc-main 当前做到哪一步了”
- “最近改了哪些文件”
- “为什么卡住了”

期望：
- Feishu 自建机器人 返回当前任务阶段、最近摘要、最近改动文件、阻塞点、审批状态、上下文压力

### 5.2 场景二：任务无进展卡顿

定义：
- 一段时间内无新 transcript / turn 事件
- 无文件变更
- 无测试/命令输出增长

期望：
- Watchdog 自动触发一次 soft steer
- 若仍无进展，则升级为飞书提醒
- 若持续无进展，则执行 handoff / resume

### 5.3 场景三：任务等待下一步指示

定义：
- Codex 输出等待用户决策，但当前任务目标本身已明确

期望：
- 在目标清晰且风险可控时，系统自动要求 Codex 选择“最小风险、最小变更”路径继续执行
- 若任务目标不清晰，则在飞书中请求人工决策

### 5.4 场景四：循环失败 / 原地打转

定义：
- 同类错误连续出现多次
- 同一命令反复执行但无有效文件变化
- 最近两次摘要高度重复

期望：
- 自动打断循环
- 要求 Codex 总结根因、提出最多 2 个修复方向、选择最小变更方案继续
- 达到严重阈值时通知人工接管

### 5.5 场景五：上下文压力过高 / 线程退化

定义：
- 会话上下文占用高
- 线程响应质量显著退化
- 出现需要压缩/恢复/新线程续跑的信号

期望：
- 自动生成 handoff summary
- 自动尝试 resume
- 若必要则创建新线程并基于 handoff 继续

### 5.6 场景六：审批请求

定义：
- Codex 请求更高权限、网络访问、工作区外访问或高破坏性操作

期望：
- Watchdog 对请求做 L0/L1/L2/L3 风险分级
- 低风险自动通过
- 中风险飞书提醒人工审批
- 高风险强制人工审批

---

## 6. 任务状态模型

### 6.1 任务主状态

枚举：
- `created`
- `running`
- `waiting_for_direction`
- `waiting_for_approval`
- `stuck`
- `handoff_in_progress`
- `resuming`
- `paused`
- `completed`
- `failed`

### 6.2 任务阶段（phase）

建议枚举：
- `planning`
- `code_reading`
- `editing_source`
- `editing_tests`
- `running_tests`
- `debugging`
- `summarizing`
- `handoff`

### 6.3 任务状态对象

```json
{
  "project_id": "ai-sdlc-main",
  "thread_id": "thr_xxx",
  "task_title": "修复 close-check planned batch completion truth",
  "status": "running",
  "phase": "editing_tests",
  "last_progress_at": "2026-04-03T14:20:00+09:00",
  "last_summary": "已修改 close_check.py，正在补 test_close_check.py",
  "files_touched": [
    "src/ai_sdlc/core/close_check.py",
    "tests/unit/test_close_check.py"
  ],
  "pending_approval": false,
  "approval_risk": null,
  "context_pressure": "medium",
  "stuck_level": 0,
  "failure_count": 1,
  "last_error_signature": null
}
```

### 6.4 context_pressure

枚举：
- `low`
- `medium`
- `high`
- `critical`

### 6.5 stuck_level

枚举：
- `0`：正常
- `1`：轻度无进展
- `2`：已自动 steer
- `3`：已升级提醒
- `4`：已进入 handoff / resume

---

## 7. 审批风险模型

### 7.1 风险等级定义

#### L0：自动通过
条件：
- 仅限工作区内读写
- 无网络
- 无系统配置变更
- 无凭证访问
- 非 destructive

例子：
- 修改代码
- 运行本地测试
- 生成仓库内临时文件

#### L1：自动通过并通知
条件：
- 工作区内操作
- 副作用可逆
- 不涉及系统级修改

例子：
- `git checkout -b ...`
- `git add`
- 覆盖测试快照
- 生成本地构建产物

#### L2：人工审批
条件：
- 需要网络
- 需要访问工作区外文件
- 可能影响外部系统
- 不在白名单中的执行行为

例子：
- `npm install`
- `uv pip install`
- 拉取外部依赖
- 调用外部 API

#### L3：强制人工审批
条件：
- 高破坏性
- 高敏感
- 对外发布型
- 系统级配置修改

例子：
- `rm -rf`
- 修改 shell profile / launch agents / 系统目录
- `git push`
- release / publish
- 写入 token / secret
- 关闭沙箱、绕过审批

### 7.2 审批对象

```json
{
  "approval_id": "appr_001",
  "project_id": "ai-sdlc-main",
  "thread_id": "thr_xxx",
  "risk_level": "L2",
  "command": "uv pip install -r requirements-dev.txt",
  "reason": "需要安装测试依赖以运行集成测试",
  "requested_at": "2026-04-03T14:25:00+09:00",
  "alternative": "如不允许联网安装，则仅执行静态检查并输出缺失依赖列表",
  "status": "pending"
}
```

---

## 8. 自动处理策略

### 8.1 无进展卡顿阈值

默认阈值：
- 3 分钟：轻度无进展，仅记录
- 8 分钟：自动 soft steer
- 15 分钟：升级飞书提醒
- 25 分钟：执行 handoff + resume

### 8.2 循环失败阈值

默认阈值：
- 同类错误 2 次：记录
- 同类错误 3 次：自动 break-loop steer
- 同类错误 5 次：暂停并提醒人工接管

### 8.3 上下文压力阈值

默认阈值：
- `medium`：记录
- `high`：自动摘要一次
- `critical`：自动 handoff + resume

### 8.4 自动 steer 模板

#### 8.4.1 soft steer

```text
请汇总当前进展：
1. 已完成内容
2. 当前阻塞点
3. 下一步最小动作
如果无阻塞，请立即继续执行。
```

#### 8.4.2 waiting-for-direction steer

```text
在不改变当前任务目标的前提下，自行选择最小风险、最小变更的继续路径，并继续执行。
如果存在多个方向，只选择最保守的一种。
```

#### 8.4.3 break-loop steer

```text
停止重复尝试。
请先总结根因，给出最多两个修复方向，选择最小变更方案后继续。
```

#### 8.4.4 handoff summary prompt

```text
请生成当前任务的 handoff summary，必须包含：
1. 当前目标
2. 已完成内容
3. 已修改文件
4. 当前阻塞点
5. 下一步建议
6. 任何待审批事项
输出为结构化 markdown。
```

---

## 9. Codex runtime service API 设计

### 9.1 设计原则

1. 对 B 暴露业务化 API，不暴露 Codex 原始细节
2. 所有接口必须带鉴权
3. 所有写操作必须审计
4. 所有接口返回统一 envelope

### 9.2 通用响应格式

```json
{
  "success": true,
  "request_id": "req_xxx",
  "data": {},
  "error": null,
  "ts": "2026-04-03T14:30:00+09:00"
}
```

### 9.3 接口列表

#### 9.3.1 创建任务

`POST /api/v1/tasks`

请求体：
```json
{
  "project_id": "ai-sdlc-main",
  "cwd": "/Users/sinclairpan/project/Ai_AutoSDLC",
  "task_title": "修复 close-check planned batch completion truth",
  "task_prompt": "...",
  "model": "gpt-5.4",
  "sandbox": "workspace-write",
  "approval_policy": "on-request"
}
```

返回：
```json
{
  "project_id": "ai-sdlc-main",
  "thread_id": "thr_xxx",
  "status": "running"
}
```

#### 9.3.2 查询任务状态

`GET /api/v1/tasks/{project_id}`

返回：任务状态对象

#### 9.3.3 注入 steer

`POST /api/v1/tasks/{project_id}/steer`

请求体：
```json
{
  "message": "请先汇总当前进展并继续推进",
  "source": "watchdog",
  "reason": "stuck_soft"
}
```

#### 9.3.4 执行 handoff

`POST /api/v1/tasks/{project_id}/handoff`

请求体：
```json
{
  "reason": "context_critical"
}
```

返回：
```json
{
  "handoff_file": "/path/to/session_handoff.md",
  "summary": "..."
}
```

#### 9.3.5 resume 任务

`POST /api/v1/tasks/{project_id}/resume`

请求体：
```json
{
  "mode": "resume_or_new_thread",
  "handoff_summary": "..."
}
```

#### 9.3.6 获取待审批请求

`GET /api/v1/approvals?status=pending`

#### 9.3.7 处理审批

`POST /api/v1/approvals/{approval_id}/decision`

请求体：
```json
{
  "decision": "approve",
  "operator": "watchdog",
  "note": "L1 自动批准"
}
```

#### 9.3.8 获取任务事件流（可选）

`GET /api/v1/tasks/{project_id}/events`

返回：
- 可用 SSE 或 WebSocket
- 用于 watchdog 侧更实时地感知状态变化

---

## 10. Watchdog / Policy Engine API 设计

### 10.1 给 Feishu 自建机器人 的接口

#### 10.1.1 查询进展

`GET /api/v1/watchdog/tasks/{project_id}/progress`

返回建议字段：
- status
- phase
- last_summary
- files_touched
- blockers
- pending_approval
- context_pressure
- last_progress_at

#### 10.1.2 人工审批

`POST /api/v1/watchdog/approvals/{approval_id}/decision`

#### 10.1.3 用户动作

`POST /api/v1/watchdog/tasks/{project_id}/actions`

动作枚举：
- `continue`
- `pause`
- `resume`
- `summarize`
- `force_handoff`
- `retry_with_conservative_path`

---

## 11. Feishu 自建机器人 集成要求

### 11.1 已知前提

Feishu 自建机器人 ↔ 飞书链路已存在，因此本项目不实现飞书通道接入。

### 11.2 Feishu 自建机器人 侧需要完成的集成

1. 为监管系统配置一个独立 agent 或独立命令路由
2. 当飞书收到查询/控制/审批类消息时，调用 Watchdog API
3. 将 Watchdog 返回的结构化结果转换为面向用户的自然语言
4. 对审批提醒消息支持按钮或命令式确认
5. 对不同项目支持按 `project_id` 路由

### 11.3 建议的飞书侧命令语义

#### 查询类
- `现在进展`
- `ai-sdlc-main 当前进展`
- `ai-sdlc-main 最近改了什么`
- `ai-sdlc-main 为什么卡住了`

#### 控制类
- `继续`
- `暂停 ai-sdlc-main`
- `重新总结后继续`
- `切换为保守方案继续`
- `强制 handoff`

#### 审批类
- `批准 #approval_id`
- `拒绝 #approval_id`
- `批准这次，并保持同类低风险自动通过`

---

## 12. 数据持久化设计

### 12.1 runtime 侧

建议存储：
- `tasks` 表 / 文件
- `task_events` 表 / 文件
- `approvals` 表 / 文件
- `thread_mapping` 表 / 文件
- `handoff_summaries` 文件目录

### 12.2 watchdog 侧

建议存储：
- `watchdog_snapshots`
- `watchdog_actions`
- `approval_decisions`
- `notification_history`

### 12.3 最小字段要求

#### tasks
- project_id
- thread_id
- cwd
- task_title
- status
- phase
- context_pressure
- last_progress_at
- created_at
- updated_at

#### task_events
- event_id
- project_id
- thread_id
- event_type
- event_source
- payload_json
- created_at

#### approvals
- approval_id
- project_id
- thread_id
- risk_level
- command
- reason
- alternative
- status
- requested_at
- decided_at
- decided_by

---

## 13. 安全要求

### 13.1 网络

1. Codex runtime service 不得直接暴露公网
2. A/B 之间推荐通过 Tailscale / 内网 VPN 通信
3. Codex runtime service 默认仅监听本机或私网地址
4. 所有 A/B 调用必须带 token 鉴权

### 13.2 权限边界

1. B 不得获取 A 的通用 shell 远程执行能力
2. Codex runtime service 仅提供白名单业务接口
3. 高风险命令必须人工审批
4. 严禁默认启用绕过审批与绕过沙箱的模式

### 13.3 审计

以下操作必须记录审计日志：
- 创建任务
- 自动 steer
- handoff
- resume
- 自动审批
- 人工审批
- 风险等级判定
- 用户下发控制命令

---

## 14. 非功能需求

### 14.1 性能

1. 查询进展接口 P95 < 3 秒
2. Watchdog 周期轮询最小间隔支持 30 秒，默认 2 分钟
3. 单项目状态对象获取时间 < 1 秒（不含飞书发送耗时）

### 14.2 可用性

1. Codex runtime service 异常重启后，能从持久化数据恢复 project_id ↔ thread_id 映射
2. watchdog 侧 Watchdog 异常重启后，不丢失待审批与最近动作状态
3. 当 A 不可达时，B 必须明确返回“控制链路异常”，不能假装任务仍在运行

### 14.3 可观测性

需要提供：
- 结构化日志
- 健康检查 `/healthz`
- 指标统计：任务数、卡顿次数、自动 steer 次数、审批数、恢复次数
- 可选 tracing

---

## 15. 研发实施要求

### 15.1 技术栈建议

Codex runtime service 可选：
- Python + FastAPI
- Node.js + Fastify / Express

Watchdog / Policy Engine 可选：
- Python
- Node.js

建议原则：
- 若团队更偏后端工程化与 JSON API，优先 FastAPI
- 若更偏实时事件与 WS，Node.js 也可

### 15.2 代码结构建议

#### Codex runtime service

```text
src/
  api/
  services/
    codex_client/
    task_manager/
    approval_manager/
    handoff_manager/
    repo_watcher/
  models/
  storage/
  policies/
  main.py
```

#### Watchdog

```text
src/
  api/
  services/
    a_client/
    status_analyzer/
    risk_classifier/
    action_executor/
    notifier/
  models/
  storage/
  schedules/
  main.py
```

---

## 16. 测试要求

### 16.1 单元测试

至少覆盖：
1. 风险分级逻辑
2. stuck_level 计算逻辑
3. context_pressure 阈值逻辑
4. 自动 steer 触发逻辑
5. handoff / resume 决策逻辑
6. API 参数校验

### 16.2 集成测试

至少覆盖：
1. 创建任务 → 查询状态 → 自动 steer 全链路
2. 审批请求 → 风险分级 → 自动批准 / 人工批准 全链路
3. 上下文 critical → handoff → resume 全链路
4. A 不可达时 B 的错误处理
5. 飞书查询语义到 Watchdog API 的适配逻辑

### 16.3 模拟器要求

必须支持通过 fake / mock 的 Codex 事件流进行测试，不依赖真实长时间开发任务才能验证：
- stuck
- wait-for-direction
- repeated failure
- context critical
- approval pending

---

## 17. 验收标准

### 17.1 功能验收

1. 用户在飞书中输入“现在进展”，可返回当前任务摘要
2. 在连续 8 分钟无进展时，系统自动触发一次 steer 并留痕
3. 在出现 L1 审批请求时，系统自动批准并通知
4. 在出现 L2 审批请求时，系统通过飞书提醒人工审批
5. 在 context_pressure = critical 时，系统自动生成 handoff summary 并 resume
6. 在 Codex runtime service 重启后，原 project_id 任务仍可查询状态

### 17.2 安全验收

1. Codex runtime service 未暴露公网
2. 所有调用均有 token 校验
3. L3 命令无法自动通过
4. 所有自动动作均有审计日志

### 17.3 可靠性验收

1. Watchdog 重启后不丢待处理审批
2. A 不可达时，B 在飞书中明确告警
3. 同一任务不会被重复 handoff / resume 导致状态错乱

---

## 18. 开发里程碑建议

### M1：基础链路打通
- Codex runtime service 启动
- 创建任务 / 查询状态 API 打通
- Feishu 自建机器人 → Watchdog → Codex runtime service 查询链路打通

### M2：监管能力
- stuck 判断
- 自动 steer
- 循环失败检测
- 基础日志与审计

### M3：审批能力
- 审批对象模型
- 风险分级
- 自动批准 / 飞书提醒 / 人工回传

### M4：恢复能力
- handoff summary
- resume / 新线程续跑
- context critical 处理

### M5：加固与验收
- 健康检查
- 指标
- 异常恢复
- 完整集成测试

---

## 19. 给 Codex / Cursor 的实施提示

### 19.1 开发顺序建议

按以下顺序实现：
1. 先实现 Codex runtime service 的任务状态持久化
2. 再接 Codex app-server 的线程与事件能力
3. 再实现 Watchdog 的状态轮询与规则判断
4. 最后接 Feishu 自建机器人 的查询/控制/审批路由

### 19.2 实施原则

1. 先完成“查询进展”最小闭环
2. 再完成“自动 steer”
3. 再做审批分级
4. 最后实现 handoff / resume

### 19.3 明确禁止事项

1. 不得通过屏幕截图/OCR 监控 Codex 桌面 UI
2. 不得把 Codex runtime service 设计成任意命令执行器
3. 不得默认自动通过高风险命令
4. 不得将飞书通道逻辑与 Watchdog 核心规则强耦合

---

## 20. 后续可扩展项（非首版）

1. 多项目并发监管面板
2. 基于项目类型的差异化审批模板
3. 针对不同仓库语言栈的特定失败分类器
4. 更细颗粒度的 context compaction 策略
5. Slack / Telegram / iMessage 等多通道复用
6. 研发日报 / 自动阶段性汇总

---

## 21. 参考约束（供研发理解，不要求照抄到代码）

1. Codex 协议层应以 app-server 为核心，而不是依赖桌面 UI 观察
2. Feishu 自建机器人 与飞书通路已存在，本项目只需消费其上游消息
3. A/B 通信应遵循内网优先、最小暴露面、最小权限原则
4. 审批与沙箱必须作为系统级边界设计，不得事后补救

---

## 22. 最终交付物要求

研发完成后，至少交付以下产物：

1. Codex runtime service 服务代码
2. Watchdog / Policy Engine 服务代码
3. Feishu 自建机器人 集成适配代码或脚本
4. 配置样例（A/B 两侧）
5. 部署说明（本地 / Tailscale / 内网）
6. API 文档
7. 测试用例与测试报告
8. 审计日志样例

