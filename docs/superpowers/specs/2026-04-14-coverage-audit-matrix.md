# 覆盖性审计矩阵（需求文档 + 计划 + 架构）

> 历史快照（2026-04-14）。
> 本文档已被 `WI-048` 到 `WI-056` 的 formal closeout 替代。
> 当前真值入口：`docs/architecture/coverage-audit-closeout-status.md`
>
> 已扩展覆盖 需求文档 1/3/4/6/8-22 以及 需求文档 17.1 等章节，并补充实施计划与架构设计中仍未落地的条款。
> 非执行性条款已单列，不计入未落地统计。
> 严格规则：实现 / 验证 / 入口三者任一缺失，即判为“未落地”。

## 需求文档 区块

### 2.1 总体目标

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 任务进展可查询 |.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-16|.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:15|| 缺飞书入口/端到端验证 | 未落地 |
| `codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 任务状态可监管 |.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-16|.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:15|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 卡顿 / 等待 / 上下文压力可自动处理 |.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:13-21|.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:24-26|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 授权审批可分级自动化 |src/a_control_agent/risk/classifier.py:6|tests/test_m3_risk.py:6-28|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 线程可恢复、可续话、可追踪 |.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:12-14|.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:15-19|| 无入口 | 未落地 |

### 2.2 成功标准

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 飞书中随时查询指定项目任务进展，响应时间小于 5 秒 |src/watchdog/api/progress.py:29-65|tests/test_watchdog.py:20-44|| 缺飞书入口/端到端验证；缺少 <5 秒 性能基准验证 | 未落地 |
| `codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 无进展卡顿触发一次 引导 并记录动作 |.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:13-21|.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:24-26|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 任务目标明确时自动选择保守路径继续执行 |.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:12-20|.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:16-19|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 上下文压力高 / 线程退化时自动生成 交接摘要，并执行 续跑 或新线程续跑 |.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:12-14|.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:15-19|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 授权请求按 `L0`/`L1`/`L2`/`L3` 四级风险模型处理，`L0`/`L1` 自动，`L2`/`L3` 精确提醒人工 |src/a_control_agent/risk/classifier.py:6|tests/test_m3_risk.py:6-28|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 关键状态、审批、自动处理动作均具备可审计日志 |.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-15|.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:14-15|| 无入口 | 未落地 |

### 5. 关键业务场景

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:159-169 / ### 5.1 场景一` | 飞书查询任务进展，返回阶段、摘要、文件、阻塞点、审批状态、上下文压力 |.ai-sdlc/work-items/022-stable-session-facts/latest-summary.md:12-15|.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:15|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:170-180 / ### 5.2 场景二` | 持续无进展则升级飞书提醒并执行交接 / 续跑 | ||| 无实现、无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:182-189 / ### 5.3 场景三` | `Codex` 等待用户决策时，在目标明确且风险可控时自动走最小风险、最小变更路径 |.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:12-20|.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:16-19|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:189-189 / ### 5.3 场景三` | 若任务目标不清晰，则在飞书中请求人工决策 |||| 无实现、无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:191-201 / ### 5.4 场景四` | 同类错误连续出现或原地打转时自动打断循环，给出最多 2 个修复方向并选择最小变更方案 |.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:15-21|.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:24-26|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:201-201 / ### 5.4 场景四` | 达到严重阈值时通知人工接管 |||| 无实现、无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:203-213 / ### 5.5 场景五` | 上下文压力过高 / 线程退化时自动生成 交接摘要，并尝试 续跑；必要时新线程续跑 |.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:12-14|.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:15-19|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:217-218 / ### 5.6 场景六` | 审批请求触发条件：`Codex` 请求更高权限、网络访问、工作区外访问或高破坏性操作 |.ai-sdlc/work-items/036-feishu-control-plane-primary-surface/latest-summary.md:14-18|.ai-sdlc/work-items/036-feishu-control-plane-primary-surface/latest-summary.md:31-40|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | `L0`：低风险自动通过 |src/a_control_agent/risk/classifier.py:6|tests/test_m3_risk.py:20|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | `L1`：自动通过并通知 |src/a_control_agent/risk/classifier.py:6|tests/test_m3_risk.py:15|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | `L2`：中风险飞书提醒人工审批 |src/a_control_agent/risk/classifier.py:6|tests/test_m3_risk.py:11|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | `L3`：高风险强制人工审批 |src/a_control_agent/risk/classifier.py:6|tests/test_m3_risk.py:6|| 无入口 | 未落地 |

### 7. 审批风险模型

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:303-315 / #### L0：自动通过` | 仅能证明存在启发式分类器；工作区/网络/系统/凭据/破坏性 边界校验未证 |src/a_control_agent/risk/classifier.py:6||| 实现不足/边界校验缺失；无验证；无入口 | 未落地 |
| `codex-watchdog-prd.md:316-326 / #### L1：自动通过并通知` | 仅能证明存在启发式分类器；工作区/网络/系统/凭据/破坏性/发布 边界校验未证 |src/a_control_agent/risk/classifier.py:6||| 实现不足/边界校验缺失；无验证；无入口 | 未落地 |
| `codex-watchdog-prd.md:328-339 / #### L2：人工审批` | 仅能证明存在启发式分类器；工作区/网络/系统/凭据/破坏性/发布 边界校验未证 |src/a_control_agent/risk/classifier.py:6||| 实现不足/边界校验缺失；无验证；无入口 | 未落地 |
| `codex-watchdog-prd.md:341-354 / #### L3：强制人工审批` | 仅能证明存在启发式分类器；工作区/网络/系统/凭据/破坏性/发布 边界校验未证 |src/a_control_agent/risk/classifier.py:6||| 实现不足/边界校验缺失；无验证；无入口 | 未落地 |

### 7.2 审批对象

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:356-369 / ### 7.2 审批对象` | 审批对象应包含 `approval_id` / `project_id` / `thread_id` / `risk_level` / `command` / `reason` / `requested_at` / `alternative` / `status` 等字段 |src/a_control_agent/storage/approvals_store.py:81||| 无验证、无入口 | 未落地 |

### 3. 项目范围

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:61-73 / ### 3.1 范围内` | 监管、查询、控制、审批、恢复属于首版范围 |src/a_control_agent/main.py:123-132||| 无验证、无入口 | 未落地 |

### 4. 总体方案

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:88-112 / ### 4.1 架构原则` | 对外暴露业务化 接口、统一 信封、强制鉴权、写操作审计 |src/a_control_agent/envelope.py:12-27||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:97-112 / ### 4.2 总体架构图` | `A`/`B` 双机通过受控 接口 和后台循环协作 |src/a_control_agent/main.py:123-132||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:113-155 / ### 4.3 组件职责` | `A` 负责任务/审批/恢复，`B` 负责监管/控制/恢复编排 |src/a_control_agent/api/tasks.py:47-267||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:113-155 / ### 4.3 组件职责` | `B` 负责进展查询、监督扫描、审批桥接、复原与运维接口 |src/watchdog/api/progress.py:29-65||| 无验证、无入口 | 未落地 |

### 6. 任务状态模型

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:230-243 / ### 6.1 任务主状态` | 任务主状态枚举不一致：当前实现仍出现 `waiting_human` / `approval` 等实现态，尚未证明需求文档原文 `waiting_for_direction` / `waiting_for_approval` / `stuck` / `handoff_in_progress` / `resuming` 全量覆盖 |src/a_control_agent/storage/tasks_store.py:196-230|tests/test_a_control_agent.py:183-258|| 枚举不一致（实现/验证缺口）；无入口 | 未落地 |
| `codex-watchdog-prd.md:244-255 / ### 6.2 任务阶段（phase）` | 任务阶段枚举不一致：当前实现仍偏向 `planning` / `approval` / `recovery` 等实现态，尚未证明需求文档原文 `code_reading` / `editing_tests` / `running_tests` / `debugging` / `summarizing` / `handoff` 全量覆盖 |src/a_control_agent/storage/tasks_store.py:196-230|tests/test_a_control_agent.py:153-258|| 枚举不一致（实现/验证缺口）；无入口 | 未落地 |
| `codex-watchdog-prd.md:256-279 / ### 6.3 任务状态对象` | 任务状态对象需包含 `project_id` / `thread_id` / `status` / `phase` / `last_progress_at` / `last_summary` / `files_touched` / `pending_approval` / `approval_risk` / `context_pressure` / `stuck_level` / `failure_count` / `last_error_signature` |src/a_control_agent/storage/tasks_store.py:196-230||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:280-287 / ### 6.4 上下文压力` | 上下文压力需覆盖 `low` / `medium` / `high` / `critical` |src/a_control_agent/storage/tasks_store.py:196-230|tests/test_m4_agent_recovery.py:11-38|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:288-297 / ### 6.5 卡顿等级` | 卡顿等级 需覆盖 `0` / `1` / `2` / `3` / `4` |src/a_control_agent/storage/tasks_store.py:196-230|tests/test_m2_stuck.py:14-75|| 无入口 | 未落地 |

### 8. 自动处理策略

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:376-383 / ### 8.1 无进展卡顿阈值` | 需要能按阈值识别无进展卡顿并触发 软引导 |src/watchdog/services/status_analyzer/stuck.py:27-75|tests/test_m2_stuck.py:14-19|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:384-390 / ### 8.2 循环失败阈值` | 需要能识别同类错误重复出现并升级处理 |src/a_control_agent/storage/tasks_store.py:546-603|tests/test_m2_stuck.py:30-75|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:391-397 / ### 8.3 上下文压力阈值` | 上下文压力 达到 严重 时必须进入恢复路径 |src/a_control_agent/api/recovery.py:31-234|tests/test_m4_watchdog_recover.py:41-75|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:400-408 / #### 8.4.1 软引导` | 软引导 模板 |src/watchdog/services/action_executor/steer.py:9-15|tests/test_a_control_agent_control_flow.py:96-116|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:410-415 / #### 8.4.2 等待指引引导` | 等待指引引导 模板 |||| 无实现、无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:417-422 / #### 8.4.3 打断循环引导` | 打断循环引导 模板 |||| 无实现、无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:424-435 / #### 8.4.4 交接摘要提示` | 交接摘要提示模板 |src/a_control_agent/storage/handoff_manager.py:13-48|tests/test_m4_agent_recovery.py:11-38|| 无入口 | 未落地 |

### 10. `Watchdog` / 策略引擎 接口 设计

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:587-598 / ### 10.1.3 用户动作` | 需求文档 `force_handoff` 目前无稳定动作代码映射 |||| 实现缺口：无稳定动作代码映射；无验证；无入口 | 未落地 |
| `codex-watchdog-prd.md:587-598 / ### 10.1.3 用户动作` | 需求文档 `pause` 目前无稳定动作代码映射 |||| 实现缺口：无稳定动作代码映射；无验证；无入口 | 未落地 |
| `codex-watchdog-prd.md:587-598 / ### 10.1.3 用户动作` | 需求文档 `summarize` 目前无稳定动作代码映射 |||| 实现缺口：无稳定动作代码映射；无验证；无入口 | 未落地 |
| `codex-watchdog-prd.md:587-598 / ### 10.1.3 用户动作` | 需求文档 `retry_with_conservative_path` 目前无稳定动作代码映射 |||| 实现缺口：无稳定动作代码映射；无验证；无入口 | 未落地 |

### 11. `Feishu` 集成要求

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:607-613 / ### 11.2 Feishu 侧需要完成的集成` | `Feishu` 侧需把飞书消息转成 `Watchdog` 接口调用并做项目路由 |examples/codex_watchdog_client.py:75-81||| 无验证；缺运行时入口/自然语言映射 | 未落地 |
| `codex-watchdog-prd.md:615-635 / ### 11.3 建议的飞书侧命令语义` | 查询、控制、审批类命令需要有稳定语义映射 |examples/codex_watchdog_client.py:75-81||| 无验证；缺运行时入口/自然语言映射 | 未落地 |

### 12. 数据持久化设计

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:639-646 / ### 12.1 runtime 侧` | `A` 侧需持久化任务、事件、审批、映射与交接摘要 |src/a_control_agent/storage/tasks_store.py:196-230||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:648-655 / ### 12.2 watchdog 侧` | `B` 侧需持久化 `Watchdog` 状态、动作、审批决策与通知历史 |src/watchdog/main.py:226-230||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:656-691 / ### 12.3 最小字段要求` | `tasks` / `task_events` / `approvals` 字段集必须可落地 |src/a_control_agent/storage/tasks_store.py:196-230||| 无验证、无入口 | 未落地 |

### 13. 安全要求

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:696-701 / ### 13.1 网络` | `A`/`B` 调用需受 令牌 鉴权，服务需走受控入口 |src/a_control_agent/api/deps.py:4-10||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:703-708 / ### 13.2 权限边界` | `B` 不得获得任意 命令行 能力，高风险命令必须人工审批 |src/a_control_agent/api/approvals.py:27-158|tests/test_m3_risk.py:6-28|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:710-720 / ### 13.3 审计` | 创建任务、引导、交接、续跑、审批与控制命令都要留审计 |src/a_control_agent/api/tasks.py:217-267||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:908-913 / ### 19.3 明确禁止事项` | 禁止桌面文字识别（`OCR`）、任意命令执行、默认自动通过高风险命令、飞书逻辑与核心规则强耦合 |||| 无实现、无验证、无入口 | 未落地 |

### 14. 非功能需求

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:726-730 / ### 14.1 性能` | 进展查询需快、轮询间隔可控、状态对象读取需足够快 |src/watchdog/api/progress.py:29-65||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:732-736 / ### 14.2 可用性` | 服务重启后需从持久化数据恢复映射与待处理状态 |src/a_control_agent/main.py:79-132||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:738-744 / ### 14.3 可观测性` | 结构化日志、健康检查、指标、任务与审批指标都需要提供 |src/a_control_agent/main.py:127-138||src/a_control_agent/main.py:127-138| 无验证 | 未落地 |

### 15. 研发实施要求

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:750-762 / ### 15.1 技术栈建议` | 首版应基于 `Python` + `FastAPI` / `Node` 可选，但实现需保持接口化 |src/a_control_agent/main.py:1-132||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:764-798 / ### 15.2 代码结构建议` | `A`/`B` 目录结构需分出 `api`/`services`/`models`/`storage`/`main` |src/a_control_agent/main.py:1-132||| 无验证、无入口 | 未落地 |

### 16. 测试要求

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:804-812 / ### 16.1 单元测试` | 风险分级、卡顿、上下文压力、引导、交接/续跑、参数校验都要单测 |src/a_control_agent/risk/classifier.py:6-43|tests/test_m3_risk.py:6-28|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:814-821 / ### 16.2 集成测试` | 创建任务、审批、恢复、`A` 不可达、飞书语义映射都要做集成测试 |src/a_control_agent/api/tasks.py:47-267|tests/test_m3_agent_approvals.py:11-120|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:823-830 / ### 16.3 模拟器要求` | 需要能用 `fake`/`mock` 事件流覆盖 卡顿 / 等待指引 / 重复失败 / 上下文压力严重 / 审批待处理 |src/watchdog/api/supervision.py:78-162|tests/test_m2_watchdog_supervision.py:44-148|| 无入口 | 未落地 |

### 17. 验收标准

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 用户在飞书中输入“现在进展”，可返回当前任务摘要 |src/watchdog/api/progress.py:29-65|tests/test_watchdog.py:12-44|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在连续 8 分钟无进展时，系统自动触发一次 引导 并留痕 |src/watchdog/services/status_analyzer/stuck.py:27-75|tests/test_m2_watchdog_supervision.py:44-79|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在出现 `L1` 审批请求时，系统自动批准并通知 |src/a_control_agent/risk/classifier.py:6-43|tests/test_m3_agent_approvals.py:32-49|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在出现 `L2` 审批请求时，系统通过飞书提醒人工审批 |src/a_control_agent/api/approvals.py:71-158|tests/test_m3_agent_approvals.py:51-75|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在 上下文压力 = 严重 时，系统自动生成 交接摘要 并 续跑 |src/a_control_agent/api/recovery.py:31-234|tests/test_m4_agent_recovery.py:11-38|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在 `Codex runtime service` 重启后，原 `project_id` 任务仍可查询状态 |src/a_control_agent/main.py:115-132||| 无验证/重启验证缺失；无入口 | 未落地 |
| `codex-watchdog-prd.md:845-850 / ### 17.2 安全验收` | 未暴露公网、令牌 校验、`L3` 不得自动通过、所有自动动作需留痕 |src/a_control_agent/api/deps.py:4-10|tests/test_m3_risk.py:6-28|| 无入口 | 未落地 |
| `codex-watchdog-prd.md:852-857 / ### 17.3 可靠性验收` | 重启不丢审批、`A` 不可达要明确告警、交接/续跑 不应错乱 |src/watchdog/main.py:65-103|tests/test_m4_agent_recovery.py:11-38|| 无入口 | 未落地 |

### 22. 最终交付物要求

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | `A` 服务 |src/a_control_agent/main.py:123-132||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | `Watchdog` 服务 |src/watchdog/main.py:181-300||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | 集成代码 |examples/codex_watchdog_client.py:75-166||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | 配置样例 |config/examples/a-agent.env.example:1-10||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | 入门文档 |README.md:5-14||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | 接口文档 |scripts/export_openapi.py:2-29||| 无验证、无入口 | 未落地 |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | 测试用例与测试报告 |tests/test_watchdog_audit.py:10-93|.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:15|| 无入口；无测试报告样例 | 未落地 |
| `codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | 审计日志样例 |tests/_watchdog_audit_fixtures.py:58-220|tests/test_watchdog_audit.py:10-93|| 无入口 | 未落地 |

## 约束 / 非执行性条款

> 这些条款属于范围外、非首版或供研发理解内容，不计入未落地矩阵。

| 来源 | 条款摘要 | 说明 |
| --- | --- | --- |
| `codex-watchdog-prd.md:1-14 / 文档基本信息与已知前提` | 文档名称、版本、日期、状态、适用范围与已知前提 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:18-31 / ## 1. 项目背景` | 用户使用方式、当前痛点与总体动机 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:74-84 / ### 3.2 范围外` | 飞书机器人、`Feishu` 渠道插件本身的安装与接入 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:74-84 / ### 3.2 范围外` | `A` 机桌面界面层级的视觉监控或自动点击 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:74-84 / ### 3.2 范围外` | 完全无人值守地自动批准所有高风险命令 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:74-84 / ### 3.2 范围外` | 代码推送（`git push`）/发布流程自动化 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:74-84 / ### 3.2 范围外` | 远程桌面控制、通用 `SSH` 运维入口 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:74-84 / ### 3.2 范围外` | 对 `Feishu` 核心代码进行深度侵入式修改（优先通过外置服务集成） | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:603-605 / ### 11.1 已知前提` | `Feishu` 与飞书链路已存在，本项目不重做通道接入 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:917-925 / ## 20. 后续可扩展项（非首版）` | 多项目并发监管面板 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:917-925 / ## 20. 后续可扩展项（非首版）` | 基于项目类型的差异化审批模板 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:917-925 / ## 20. 后续可扩展项（非首版）` | 针对不同仓库语言栈的特定失败分类器 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:917-925 / ## 20. 后续可扩展项（非首版）` | 更细颗粒度的上下文压缩策略 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:917-925 / ## 20. 后续可扩展项（非首版）` | `Slack`/`Telegram`/`iMessage` 等多通道复用 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:917-925 / ## 20. 后续可扩展项（非首版）` | 研发日报 / 自动阶段性汇总 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:928-933 / ## 21. 参考约束（供研发理解，不要求照抄到代码）` | 协议层以应用服务器（`app-server`）为核心、消费上游消息、内网优先、最小暴露面、审批与沙箱为系统级边界 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:862-865 / ### M1：基础链路打通` | `A` 启动、任务创建 / 查询、`Feishu`→`Watchdog`→`A` 查询链路打通 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:867-871 / ### M2：监管能力` | 卡顿判断、自动引导、循环失败检测、基础日志与审计 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:873-876 / ### M3：审批能力` | 审批对象模型、风险分级、自动批准 / 提醒 / 回传 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:878-881 / ### M4：恢复能力` | 交接摘要、续跑 / 新线程续跑、上下文压力严重处理 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:883-887 / ### M5：加固与验收` | 健康检查、指标、异常恢复、完整集成测试 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:893-899 / ### 19.1 开发顺序建议` | 先任务状态持久化，再线程事件，再监管规则，最后 `Feishu` 路由 | 非执行性条款（不计入未落地） |
| `codex-watchdog-prd.md:901-906 / ### 19.2 实施原则` | 先查询进展，再自动引导，再审批分级，最后交接 / 续跑 | 非执行性条款（不计入未落地） |

## 实施计划区块

### 验收顺序未落地条款

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:405 / 验收顺序` | 所有 副作用 必须先经过 会话事件写入闸门 |.ai-sdlc/work-items/030-session-service-event-truth-write-barrier/latest-summary.md:12||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:406 / 验收顺序` | 审批/通知/人工覆盖不可再有独立真源，命令 租约 需具备恢复协议 |.ai-sdlc/work-items/030-session-service-event-truth-write-barrier/latest-summary.md:12||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:407 / 验收顺序` | `session_spine`/审批收件箱/通知状态/审计查询必须优先读事件投影 |.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-13||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:408 / 验收顺序` | `Goal Contract` 成为显式持久化对象，`AI_AutoSDLC` 只作为上下文来源 |.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:12-15||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:409 / 验收顺序` | 远程压缩等问题必须走恢复事务 |.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:12-14||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:410 / 验收顺序` | `Memory Hub` 需以独立 契约 提供 常驻/会话检索/技能/输入包 能力 |.ai-sdlc/work-items/034-memory-hub-codex-critical/latest-summary.md:13-15||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:410 / 验收顺序` | 用户模型/周期提示 仅可作为 辅助预览，不得覆盖 会话真相/`Goal Contract` |.ai-sdlc/work-items/034-memory-hub-codex-critical/latest-summary.md:13-15||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:411 / 验收顺序` | 长期记忆写入遵循基线建档+增量摄取+溯源+安全裁定 |.ai-sdlc/work-items/034-memory-hub-codex-critical/latest-summary.md:13-16||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:411 / 验收顺序` | `Watchdog`/`Codex` 主路径已接入 `Memory Hub`，预览入口不阻塞一期放行 |.ai-sdlc/work-items/034-memory-hub-codex-critical/latest-summary.md:13-16||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:411 / 验收顺序` | `Memory Hub` 不可用/冲突必须写入 规范事件 后再降级 |.ai-sdlc/work-items/034-memory-hub-codex-critical/latest-summary.md:13-16||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:412 / 验收顺序` | `Brain` 具备提供方认证、回放、决策校验与低风险闭环 |.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:13-20||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:413 / 验收顺序` | `Release Gate` 样本冻结、标注与报告归档必须脚本化 |.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:15-20||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:414 / 验收顺序` | 飞书成为唯一主控制面，`Feishu` 只保留兼容读写 |.ai-sdlc/work-items/036-feishu-control-plane-primary-surface/latest-summary.md:12-28||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:415 / 验收顺序` | 至少一条 飞书->`Goal Contract`->`Brain`->... 主链路可重复通关且产出 `release_gate_report` |.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:14-23||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:416 / 验收顺序` | 未来执行体/子代理只以规范执行契约存在 |.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md:14-17||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:417 / 验收顺序` | 声明式请求、同迹回放/消费、晚到结果拒绝都需失败即关闭 |.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md:27-33||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:418 / 验收顺序` | `release_gate_report` 共享加载接口与证据包只能有一套 |.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/latest-summary.md:27-29||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:419 / 验收顺序` | 后续入口必须复用共享加载/证据包契约 |.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/latest-summary.md:27-29||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:420 / 验收顺序` | `release_gate_report` 材料、`report_id` 种子与 `hash` 只有一套共享契约 |.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/latest-summary.md:27-29||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:421 / 验收顺序` | 报告刷新或夹具更新必须复用共享辅助函数 |.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/latest-summary.md:27-29||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:422 / 验收顺序` | 刷新/重建/夹具再生成 只有一个正式命令入口 |.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/latest-summary.md:29-31||| 无验证、无入口 | 未落地 |
| `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md:423 / 验收顺序` | 运行手册与契约测试正式化刷新成功态与漂移纪律 |.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/latest-summary.md:29-31||| 无验证、无入口 | 未落地 |

## 架构设计区块

| 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `docs/architecture/codex-watchdog-full-product-loop-design.md:20-25 / 稳定脊柱现状与闭环缺口` | 当前仍是稳定脊柱最小可用版本，自动决策与生产化闭环缺口未补齐 |||| 无实现、无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:285-316 / Brain 必备能力` | `Brain` 必须具备策略闸门 / 输入构建 / 目标闭环判定 / 恢复 / 校验 / 认证 / 回放 / `Release Gate` 八大能力闭环 |.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:13-20||| 无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:51 / 旧读面降级为 projection` | `session_spine`/`tasks_store`/`audit` 只能作为投影/外观，不能再与新系统并行真源 |.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-14||| 无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:921-932 / Release Gate 放行门槛` | 低风险自动决策必须满足明确量化门槛（覆盖场景、成功率、漂移率等） |.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:14-16||| 无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:934-939 / Release Gate 放行规则` | 未达门槛或回归失败必须降级为仅观察/仅建议 |.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:15-20||| 无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:943-951 / Release Gate 证据包` | 必须有证据包与 `release_gate_report`，缺失报告不得放行 |.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:14-16||| 无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:339 / Memory Hub 成功标准` | 支撑远程压缩与跨会话交接的连续性 |||| 无实现、无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:340 / Memory Hub 成功标准` | 项目事实/恢复案例/技能候选需稳定提供给 `Brain` |||| 无实现、无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:341 / Memory Hub 成功标准` | `AI_AutoSDLC` 阶段感知模式保留但不纳入一期放行门槛 |||| 无实现、无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:342 / Memory Hub 成功标准` | 四层记忆仅交付最小可用切片，不做通用知识平台 |||| 无实现、无验证、无入口 | 未落地 |
| `docs/architecture/codex-long-running-autonomy-design.md:343 / Memory Hub 成功标准` | 不能提升接续/自动决策/技能复用/解释性的功能不进入一期 |||| 无实现、无验证、无入口 | 未落地 |

## 结论

> 统计口径：仅统计 需求文档/计划/架构区块内“结论=未落地”的条款；不包含“非执行性条款”区块。

未落地条款总数：115

| 缺口类型 | 数量 |
| --- | --- |
| 无验证、无入口 | 49 |
| 无入口 | 37 |
| 无实现、无验证、无入口 | 12 |
| 实现缺口：无稳定动作代码映射；无验证；无入口 | 4 |
| 实现不足/边界校验缺失；无验证；无入口 | 4 |
| 无验证 | 1 |
| 枚举不一致（实现/验证缺口）；无入口 | 2 |
| 无验证；缺运行时入口/自然语言映射 | 2 |
| 缺飞书入口/端到端验证 | 1 |
| 缺飞书入口/端到端验证；缺少 <5 秒 性能基准验证 | 1 |
| 无验证/重启验证缺失；无入口 | 1 |
| 无入口；无测试报告样例 | 1 |
