# 覆盖性审计矩阵：PRD 区块

> 已扩展覆盖 PRD 3/4/6/8-22 以及 PRD 9、17.1 等章节，并保留 2/5/7 的核心条款行。
> 非执行性条款已单列，不计入未落地统计。
> 严格规则：实现 / 验证 / 入口三者任一缺失，即判为“未落地”。

## PRD 区块

### 2.1 总体目标

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 任务进展可查询 | `.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-16 /实现证据；.ai-sdlc/work-items/022-stable-session-facts/latest-summary.md:12-15 /实现证据` | `.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:15 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 任务状态可监管 | `.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-16 /实现证据；.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md:12-29 /实现证据` | `.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:15 /验证证据；.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md:31-40 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 卡顿 / 等待 / 上下文压力可自动处理 | `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:13-21 /实现证据` | `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:24-26 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 授权审批可分级自动化 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | `tests/test_m3_risk.py:6-28 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:37-44 / ## 2.1 总体目标` | 线程可恢复、可续话、可追踪 | `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:12-14 /实现证据；.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md:14-36 /实现证据` | `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:15-19 /验证证据；.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md:39-59 /验证证据` | — | 无入口 | 未落地 |

### 2.2 成功标准

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 飞书中随时查询指定项目任务进展，响应时间小于 5 秒 | `src/watchdog/api/progress.py:29-65 /实现证据；src/a_control_agent/api/tasks.py:135-148 /实现证据` | `tests/test_watchdog.py:20-44 /验证证据；tests/test_a_control_agent.py:93-117 /验证证据` | — | 缺少 <5 秒 性能基准验证 | 未落地 |
| `openclaw-codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 无进展卡顿触发一次 steer 并记录动作 | `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:13-21 /实现证据；.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:21-28 /实现证据` | `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:24-26 /验证证据；.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:37-40 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 任务目标明确时自动选择保守路径继续执行 | `.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:12-20 /实现证据` | `.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:16-19 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 上下文压力高 / 线程退化时自动生成 handoff summary，并执行 resume 或新线程续跑 | `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:12-14 /实现证据` | `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:15-19 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 授权请求按 L0/L1/L2/L3 四级风险模型处理，L0/L1 自动，L2/L3 精确提醒人工 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | `tests/test_m3_risk.py:6-28 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:46-55 / ## 2.2 成功标准` | 关键状态、审批、自动处理动作均具备可审计日志 | `.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-15 /实现证据；.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:15-20 /实现证据；.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:24-31 /实现证据` | `.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:14-15 /验证证据；.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:24-26 /验证证据；.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:37-40 /验证证据` | — | 无入口 | 未落地 |

### 5. 关键业务场景

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:159-169 / ### 5.1 场景一` | 飞书查询任务进展，返回阶段、摘要、文件、阻塞点、审批状态、上下文压力 | `.ai-sdlc/work-items/022-stable-session-facts/latest-summary.md:12-15 /实现证据；.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:12-16 /实现证据；.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md:21-28 /实现证据` | `.ai-sdlc/work-items/031-session-spine-events-projection-read-surface/latest-summary.md:15 /验证证据；.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md:31-40 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:170-180 / ### 5.2 场景二` | 无新进展时自动 soft steer，持续无进展则升级飞书提醒并执行 handoff / resume | `src/watchdog/services/status_analyzer/stuck.py:27 /实现证据；src/watchdog/api/supervision.py:78 /实现证据；src/watchdog/services/session_spine/recovery.py:80 /实现证据` | `tests/test_m2_stuck.py:14 /验证证据；tests/test_m2_watchdog_supervision.py:44 /验证证据；tests/test_m4_watchdog_recover.py:41 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:182-189 / ### 5.3 场景三` | Codex 等待用户决策时，在目标明确且风险可控时自动走最小风险、最小变更路径 | `.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:12-20 /实现证据` | `.ai-sdlc/work-items/032-goal-contract-persistence-and-governance/latest-summary.md:16-19 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:189-189 / ### 5.3 场景三` | 若任务目标不清晰，则在飞书中请求人工决策 | — | — | — | 无实现、无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:191-201 / ### 5.4 场景四` | 同类错误连续出现或原地打转时自动打断循环，给出最多 2 个修复方向并选择最小变更方案 | `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:15-21 /实现证据；.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:21-28 /实现证据；.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md:14-33 /实现证据` | `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md:24-26 /验证证据；.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md:37-40 /验证证据；.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md:39-59 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:201-201 / ### 5.4 场景四` | 达到严重阈值时通知人工接管 | — | — | — | 无实现、无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:203-213 / ### 5.5 场景五` | 上下文压力过高 / 线程退化时自动生成 handoff summary，并尝试 resume；必要时新线程续跑 | `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:12-14 /实现证据` | `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md:15-19 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:217-218 / ### 5.6 场景六` | 审批请求触发条件：Codex 请求更高权限、网络访问、工作区外访问或高破坏性操作 | `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md:14-18 /实现证据` | `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md:31-40 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | L0：低风险自动通过 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | `tests/test_m3_risk.py:20 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | L1：自动通过并通知 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | `tests/test_m3_risk.py:15 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | L2：中风险飞书提醒人工审批 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | `tests/test_m3_risk.py:11 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:220-224 / ### 5.6 场景六` | L3：高风险强制人工审批 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | `tests/test_m3_risk.py:6 /验证证据` | — | 无入口 | 未落地 |

### 7. 审批风险模型

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:303-315 / #### L0：自动通过` | 仅限工作区内读写、无网络、无系统配置变更、无凭证访问、非 destructive；修改代码 / 运行本地测试 / 生成临时文件 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:316-326 / #### L1：自动通过并通知` | 工作区内、可逆副作用、无系统级修改；git checkout -b / git add / 覆盖快照 / 本地构建产物 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:328-339 / #### L2：人工审批` | 需要网络、工作区外文件、外部系统影响、或不在白名单的执行行为；npm install / uv pip install / 外部依赖 / 外部 API | `src/a_control_agent/risk/classifier.py:6 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:341-354 / #### L3：强制人工审批` | 高破坏性 / 高敏感 / 对外发布型 / 系统级配置修改；rm -rf、shell profile、git push、release / publish、写入 token / secret、关闭沙箱 | `src/a_control_agent/risk/classifier.py:6 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 7.2 审批对象

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:356-369 / ### 7.2 审批对象` | 审批对象应包含 approval_id / project_id / thread_id / risk_level / command / reason / requested_at / alternative / status 等字段 | `src/a_control_agent/storage/approvals_store.py:81 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 3. 项目范围

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:61-73 / ### 3.1 In Scope` | 监管、查询、控制、审批、恢复属于首版范围 | `src/a_control_agent/main.py:123-132 /实现证据；src/watchdog/main.py:285-300 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 4. 总体方案

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:88-112 / ### 4.1 架构原则` | 对外暴露业务化 API、统一 envelope、强制鉴权、写操作审计 | `src/a_control_agent/envelope.py:12-27 /实现证据；src/a_control_agent/api/deps.py:4-10 /实现证据；src/watchdog/api/deps.py:4-10 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:97-112 / ### 4.2 总体架构图` | A/B 双机通过受控 API 和后台循环协作 | `src/a_control_agent/main.py:123-132 /实现证据；src/watchdog/main.py:181-300 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:113-155 / ### 4.3 组件职责` | A 负责任务/审批/恢复，B 负责监管/控制/恢复编排 | `src/a_control_agent/api/tasks.py:47-267 /实现证据；src/a_control_agent/api/approvals.py:27-158 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:113-155 / ### 4.3 组件职责` | B 负责进展查询、监督扫描、审批桥接、复原与运维接口 | `src/watchdog/api/progress.py:29-65 /实现证据；src/watchdog/api/supervision.py:78-162 /实现证据；src/watchdog/api/feishu_control.py:64-95 /实现证据；src/watchdog/api/recover_watchdog.py:26-57 /实现证据；src/watchdog/api/ops.py:176-423 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 6. 任务状态模型

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:230-243 / ### 6.1 任务主状态` | 任务主状态需覆盖 `created` / `running` / `waiting_for_direction` / `waiting_for_approval` / `stuck` / `handoff_in_progress` / `resuming` / `paused` / `completed` / `failed` | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据；src/watchdog/services/session_service/service.py:668-672 /实现证据` | `tests/test_a_control_agent.py:93-117 /验证证据；tests/test_m4_agent_recovery.py:11-38 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:244-255 / ### 6.2 任务阶段（phase）` | 任务阶段需覆盖 `planning` / `code_reading` / `editing_source` / `editing_tests` / `running_tests` / `debugging` / `summarizing` / `handoff` | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据` | `tests/test_a_control_agent.py:153-184 /验证证据；tests/test_m4_agent_recovery.py:11-38 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:256-279 / ### 6.3 任务状态对象` | 任务状态对象需包含 cwd / title / prompt / model / sandbox / approval_policy / summary / files / pending_approval 等字段 | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:280-287 / ### 6.4 context_pressure` | context_pressure 需覆盖 `low` / `medium` / `high` / `critical` | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据` | `tests/test_m4_agent_recovery.py:11-38 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:288-297 / ### 6.5 stuck_level` | stuck_level 需覆盖 `0` / `1` / `2` / `3` / `4` | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据；src/watchdog/services/status_analyzer/stuck.py:27-75 /实现证据` | `tests/test_m2_stuck.py:14-75 /验证证据` | — | 无入口 | 未落地 |

### 8. 自动处理策略

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:376-383 / ### 8.1 无进展卡顿阈值` | 需要能按阈值识别无进展卡顿并触发 soft steer | `src/watchdog/services/status_analyzer/stuck.py:27-75 /实现证据；src/watchdog/api/supervision.py:78-162 /实现证据` | `tests/test_m2_stuck.py:14-19 /验证证据；tests/test_m2_watchdog_supervision.py:44-79 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:384-390 / ### 8.2 循环失败阈值` | 需要能识别同类错误重复出现并升级处理 | `src/a_control_agent/storage/tasks_store.py:546-603 /实现证据；src/watchdog/services/status_analyzer/stuck.py:27-75 /实现证据` | `tests/test_m2_stuck.py:30-75 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:391-397 / ### 8.3 上下文压力阈值` | context_pressure 达到 critical 时必须进入恢复路径 | `src/a_control_agent/api/recovery.py:31-234 /实现证据；src/watchdog/api/recover_watchdog.py:26-57 /实现证据；src/watchdog/services/session_spine/recovery.py:80-190 /实现证据` | `tests/test_m4_watchdog_recover.py:41-75 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:400-408 / #### 8.4.1 soft steer` | soft steer 模板 | `src/watchdog/services/action_executor/steer.py:9-15 /实现证据` | `tests/test_a_control_agent_control_flow.py:96-116 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:410-415 / #### 8.4.2 waiting-for-direction steer` | waiting-for-direction steer 模板 | — | — | — | 无实现、无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:417-422 / #### 8.4.3 break-loop steer` | break-loop steer 模板 | — | — | — | 无实现、无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:424-435 / #### 8.4.4 handoff summary prompt` | handoff summary prompt 模板 | `src/a_control_agent/storage/handoff_manager.py:13-48 /实现证据` | `tests/test_m4_agent_recovery.py:11-38 /验证证据` | — | 无入口 | 未落地 |

### 9. A-Control-Agent API 设计

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:441-446 / ### 9.1 设计原则` | 对 B 暴露业务化 API，不暴露 Codex 原始细节；所有接口必须带鉴权；所有写操作必须审计；所有接口返回统一 envelope | `src/a_control_agent/main.py:123-132 /实现证据；src/a_control_agent/envelope.py:12-29 /实现证据；src/a_control_agent/api/deps.py:4-10 /实现证据；src/a_control_agent/api/tasks.py:110-188 /实现证据` | `tests/test_a_control_agent.py:57-117 /验证证据；tests/test_a_control_agent.py:270-345 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:448-458 / ### 9.2 通用响应格式` | 返回格式应包含 `success` / `request_id` / `data` / `error` / `ts` | `src/a_control_agent/envelope.py:12-29 /实现证据；src/watchdog/envelope.py:1-3 /实现证据` | `tests/test_a_control_agent.py:110-117 /验证证据；tests/test_a_control_agent.py:266-267 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:462-487 / ### 9.3.1 创建任务` | `POST /api/v1/tasks` | `src/a_control_agent/api/tasks.py:110-132 /实现证据` | `tests/test_a_control_agent.py:93-117 /验证证据；tests/integration/test_prd_chains.py:15-37 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:488-492 / ### 9.3.2 查询任务状态` | `GET /api/v1/tasks/{project_id}` | `src/a_control_agent/api/tasks.py:135-148 /实现证据` | `tests/test_a_control_agent.py:93-117 /验证证据；tests/integration/test_prd_chains.py:15-37 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:494-505 / ### 9.3.3 注入 steer` | `POST /api/v1/tasks/{project_id}/steer` | `src/a_control_agent/api/tasks.py:217-300 /实现证据` | `tests/test_a_control_agent_control_flow.py:96-116 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:507-524 / ### 9.3.4 执行 handoff` | `POST /api/v1/tasks/{project_id}/handoff` | `src/a_control_agent/api/recovery.py:31-109 /实现证据` | `tests/test_a_control_agent_control_flow.py:142-165 /验证证据；tests/test_m4_agent_recovery.py:11-31 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:526-536 / ### 9.3.5 resume 任务` | `POST /api/v1/tasks/{project_id}/resume` | `src/a_control_agent/api/recovery.py:112-234 /实现证据` | `tests/test_a_control_agent_control_flow.py:119-139 /验证证据；tests/test_m4_agent_recovery.py:33-38 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:538-541 / ### 9.3.6 获取待审批请求` | `GET /api/v1/approvals?status=pending` | `src/a_control_agent/api/approvals.py:27-43 /实现证据` | `tests/test_m3_agent_approvals.py:51-68 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:542-553 / ### 9.3.7 处理审批` | `POST /api/v1/approvals/{approval_id}/decision` | `src/a_control_agent/api/approvals.py:71-158 /实现证据` | `tests/test_m3_agent_approvals.py:51-75 /验证证据；tests/test_a_control_agent_control_flow.py:192-224 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:555-561 / ### 9.3.8 获取任务事件流（可选）` | `GET /api/v1/tasks/{project_id}/events` | `src/a_control_agent/api/tasks.py:151-188 /实现证据` | `tests/test_a_control_agent.py:270-289 /验证证据；tests/test_a_control_agent_control_flow.py:142-189 /验证证据` | — | 无入口 | 未落地 |

### 10. Watchdog / Policy Engine API 设计

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:567-582 / ### 10.1.1 查询进展` | B 侧需要提供任务进展读取入口并在 A 不可达时明确报错 | `src/watchdog/api/progress.py:29-65 /实现证据` | — | `src/watchdog/main.py:285-300 /入口证据` | 无验证 | 未落地 |
| `openclaw-codex-watchdog-prd.md:583-586 / ### 10.1.2 人工审批` | B 侧需要提供审批决策回传入口 | `src/watchdog/api/feishu_control.py:64-95 /实现证据；src/watchdog/api/openclaw_responses.py:90-158 /实现证据` | — | `src/watchdog/main.py:285-300 /入口证据` | 无验证 | 未落地 |
| `openclaw-codex-watchdog-prd.md:587-598 / ### 10.1.3 用户动作` | B 侧需要提供 continue / pause / resume / summarize / force_handoff / retry_with_conservative_path 等动作入口 | `src/watchdog/api/session_spine_actions.py:113-367 /实现证据` | — | `src/watchdog/main.py:285-296 /入口证据` | 无验证 | 未落地 |

### 11. OpenClaw 集成要求

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:603-605 / ### 11.1 已知前提` | OpenClaw 与飞书链路已存在，本项目不重做通道接入 | `src/watchdog/api/feishu_control.py:64-95 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:607-613 / ### 11.2 OpenClaw 侧需要完成的集成` | OpenClaw 侧需把飞书消息转成 Watchdog API 调用并做项目路由 | `src/watchdog/main.py:285-296 /实现证据；src/watchdog/api/feishu_control.py:64-95 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:615-635 / ### 11.3 建议的飞书侧命令语义` | 查询、控制、审批类命令需要有稳定语义映射 | `src/watchdog/api/feishu_control.py:64-95 /实现证据；src/watchdog/api/session_spine_actions.py:113-367 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 12. 数据持久化设计

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:639-646 / ### 12.1 A 侧` | A 侧需持久化任务、事件、审批、映射与 handoff 摘要 | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据；src/a_control_agent/storage/tasks_store.py:632-650 /实现证据；src/a_control_agent/storage/approvals_store.py:66-199 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:648-655 / ### 12.2 B 侧` | B 侧需持久化 watchdog 状态、动作、审批决策与通知历史 | `src/watchdog/main.py:226-230 /实现证据；src/watchdog/services/policy/decisions.py:1-160 /实现证据；src/watchdog/services/approvals/service.py:120-260 /实现证据；src/watchdog/storage/action_receipts.py:1-80 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:656-691 / ### 12.3 最小字段要求` | tasks / task_events / approvals 字段集必须可落地 | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据；src/a_control_agent/storage/tasks_store.py:377-603 /实现证据；src/a_control_agent/storage/tasks_store.py:632-650 /实现证据；src/a_control_agent/storage/approvals_store.py:66-199 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 13. 安全要求

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:696-701 / ### 13.1 网络` | A/B 调用需受 token 鉴权，服务需走受控入口 | `src/a_control_agent/api/deps.py:4-10 /实现证据；src/watchdog/api/deps.py:4-10 /实现证据；src/a_control_agent/main.py:123-132 /实现证据；src/watchdog/main.py:285-300 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:703-708 / ### 13.2 权限边界` | B 不得获得任意 shell 能力，高风险命令必须人工审批 | `src/a_control_agent/api/approvals.py:27-158 /实现证据；src/a_control_agent/risk/classifier.py:6-43 /实现证据；src/watchdog/api/feishu_control.py:64-95 /实现证据` | `tests/test_m3_risk.py:6-28 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:710-720 / ### 13.3 审计` | 创建任务、steer、handoff、resume、审批与控制命令都要留审计 | `src/a_control_agent/api/tasks.py:217-267 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据；src/a_control_agent/api/approvals.py:71-158 /实现证据；src/watchdog/api/feishu_control.py:64-95 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 14. 非功能需求

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:726-730 / ### 14.1 性能` | 进展查询需快、轮询间隔可控、状态对象读取需足够快 | `src/watchdog/api/progress.py:29-65 /实现证据；src/a_control_agent/api/tasks.py:47-148 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:732-736 / ### 14.2 可用性` | 服务重启后需从持久化数据恢复映射与待处理状态 | `src/a_control_agent/main.py:79-132 /实现证据；src/watchdog/main.py:65-103 /实现证据；src/watchdog/main.py:226-230 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:738-744 / ### 14.3 可观测性` | 结构化日志、healthz、metrics、任务与审批指标都需要提供 | `src/a_control_agent/main.py:127-138 /实现证据；src/watchdog/main.py:299-300 /实现证据；src/watchdog/api/metrics.py:12-18 /实现证据` | — | `src/a_control_agent/main.py:127-138 /入口证据；src/watchdog/main.py:299-300 /入口证据` | 无验证 | 未落地 |

### 15. 研发实施要求

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:750-762 / ### 15.1 技术栈建议` | 首版应基于 Python + FastAPI / Node 可选，但实现需保持 API 化 | `src/a_control_agent/main.py:1-132 /实现证据；src/watchdog/main.py:1-300 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:764-798 / ### 15.2 代码结构建议` | A/B 目录结构需分出 api / services / models / storage / main | `src/a_control_agent/main.py:1-132 /实现证据；src/watchdog/main.py:1-300 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 16. 测试要求

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:804-812 / ### 16.1 单元测试` | 风险分级、stuck、context_pressure、steer、handoff/resume、参数校验都要单测 | `src/a_control_agent/risk/classifier.py:6-43 /实现证据；src/watchdog/services/status_analyzer/stuck.py:27-75 /实现证据；src/watchdog/services/session_spine/recovery.py:80-190 /实现证据` | `tests/test_m3_risk.py:6-28 /验证证据; tests/test_m2_stuck.py:14-75 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:814-821 / ### 16.2 集成测试` | 创建任务、审批、恢复、A 不可达、飞书语义映射都要做集成测试 | `src/a_control_agent/api/tasks.py:47-267 /实现证据；src/a_control_agent/api/approvals.py:27-158 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据；src/watchdog/api/progress.py:29-65 /实现证据` | `tests/test_m3_agent_approvals.py:11-120 /验证证据；tests/test_m4_watchdog_recover.py:41-95 /验证证据；tests/test_m2_watchdog_supervision.py:44-148 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:823-830 / ### 16.3 模拟器要求` | 需要能用 fake / mock 事件流覆盖 stuck / wait-for-direction / repeated failure / context critical / approval pending | `src/watchdog/api/supervision.py:78-162 /实现证据；src/watchdog/api/recover_watchdog.py:26-57 /实现证据` | `tests/test_m2_watchdog_supervision.py:44-148 /验证证据；tests/test_m4_watchdog_recover.py:41-95 /验证证据` | — | 无入口 | 未落地 |

### 17. 验收标准

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 用户在飞书中输入“现在进展”，可返回当前任务摘要 | `src/watchdog/api/progress.py:29-65 /实现证据；src/watchdog/main.py:285-288 /实现证据` | `tests/test_watchdog.py:12-44 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在连续 8 分钟无进展时，系统自动触发一次 steer 并留痕 | `src/watchdog/services/status_analyzer/stuck.py:27-75 /实现证据；src/watchdog/api/supervision.py:78-162 /实现证据` | `tests/test_m2_watchdog_supervision.py:44-79 /验证证据；tests/test_m2_watchdog_supervision.py:82-148 /验证证据；tests/integration/test_prd_chains.py:72-106 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在出现 L1 审批请求时，系统自动批准并通知 | `src/a_control_agent/risk/classifier.py:6-43 /实现证据；src/a_control_agent/storage/approvals_store.py:66-199 /实现证据；src/a_control_agent/api/approvals.py:46-68 /实现证据` | `tests/test_m3_agent_approvals.py:32-49 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在出现 L2 审批请求时，系统通过飞书提醒人工审批 | `src/a_control_agent/api/approvals.py:71-158 /实现证据；src/watchdog/api/feishu_control.py:64-95 /实现证据` | `tests/test_m3_agent_approvals.py:51-75 /验证证据；tests/test_a_control_agent_control_flow.py:192-224 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在 context_pressure = critical 时，系统自动生成 handoff summary 并 resume | `src/a_control_agent/api/recovery.py:31-234 /实现证据；src/a_control_agent/storage/handoff_manager.py:13-48 /实现证据` | `tests/test_m4_agent_recovery.py:11-38 /验证证据；tests/test_watchdog_recovery_execution.py:93-165 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:836-843 / ### 17.1 功能验收` | 在 A-Control-Agent 重启后，原 project_id 任务仍可查询状态 | `src/a_control_agent/main.py:115-132 /实现证据；src/a_control_agent/storage/tasks_store.py:196-230 /实现证据` | `tests/test_a_control_agent.py:93-117 /验证证据；tests/test_m4_agent_recovery.py:11-38 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:845-850 / ### 17.2 安全验收` | 未暴露公网、token 校验、L3 不得自动通过、所有自动动作需留痕 | `src/a_control_agent/api/deps.py:4-10 /实现证据；src/watchdog/api/deps.py:4-10 /实现证据；src/a_control_agent/risk/classifier.py:6-43 /实现证据；src/a_control_agent/storage/tasks_store.py:477-603 /实现证据` | `tests/test_m3_risk.py:6-28 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:852-857 / ### 17.3 可靠性验收` | 重启不丢审批、A 不可达要明确告警、handoff/resume 不应错乱 | `src/watchdog/main.py:65-103 /实现证据；src/watchdog/api/progress.py:29-65 /实现证据；src/a_control_agent/api/recovery.py:31-234 /实现证据` | `tests/test_m4_agent_recovery.py:11-38 /验证证据；tests/test_watchdog_recovery_execution.py:93-165 /验证证据` | — | 无入口 | 未落地 |

### 18. 开发里程碑建议

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:862-865 / ### M1：基础链路打通` | A 启动、任务创建 / 查询、OpenClaw→Watchdog→A 查询链路打通 | `src/a_control_agent/main.py:79-132 /实现证据；src/a_control_agent/api/tasks.py:47-148 /实现证据；src/watchdog/api/progress.py:29-65 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:867-871 / ### M2：监管能力` | stuck 判断、自动 steer、循环失败检测、基础日志与审计 | `src/watchdog/services/status_analyzer/stuck.py:27-75 /实现证据；src/watchdog/api/supervision.py:78-162 /实现证据；src/a_control_agent/storage/tasks_store.py:477-603 /实现证据` | `tests/test_m2_stuck.py:14-75 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:873-876 / ### M3：审批能力` | 审批对象模型、风险分级、自动批准 / 提醒 / 回传 | `src/a_control_agent/storage/approvals_store.py:66-199 /实现证据；src/a_control_agent/risk/classifier.py:6-43 /实现证据; src/watchdog/api/feishu_control.py:64-95 /实现证据` | `tests/test_m3_agent_approvals.py:11-120 /验证证据; tests/test_m3_risk.py:6-28 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:878-881 / ### M4：恢复能力` | handoff summary、resume / 新线程续跑、context critical 处理 | `src/a_control_agent/api/recovery.py:31-234 /实现证据; src/watchdog/api/recover_watchdog.py:26-57 /实现证据; src/watchdog/services/session_spine/recovery.py:80-190 /实现证据` | `tests/test_m4_watchdog_recover.py:41-95 /验证证据` | — | 无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:883-887 / ### M5：加固与验收` | healthz、指标、异常恢复、完整集成测试 | `src/a_control_agent/main.py:127-138 /实现证据; src/watchdog/main.py:299-300 /实现证据; src/watchdog/api/metrics.py:12-18 /实现证据` | — | `src/a_control_agent/main.py:127-138 /入口证据; src/watchdog/main.py:299-300 /入口证据` | 无验证 | 未落地 |

### 19. 给 Codex / Cursor 的实施提示

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:893-899 / ### 19.1 开发顺序建议` | 先任务状态持久化，再线程事件，再监管规则，最后 OpenClaw 路由 | `src/a_control_agent/storage/tasks_store.py:196-230 /实现证据；src/watchdog/api/supervision.py:78-162 /实现证据; src/watchdog/main.py:285-296 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:901-906 / ### 19.2 实施原则` | 先查询进展，再自动 steer，再审批分级，最后 handoff / resume | `src/watchdog/api/progress.py:29-65 /实现证据; src/watchdog/api/supervision.py:78-162 /实现证据; src/a_control_agent/api/approvals.py:27-158 /实现证据; src/a_control_agent/api/recovery.py:31-234 /实现证据` | — | — | 无验证、无入口 | 未落地 |
| `openclaw-codex-watchdog-prd.md:908-913 / ### 19.3 明确禁止事项` | 禁止桌面 OCR、任意命令执行、默认自动通过高风险命令、飞书逻辑与核心规则强耦合 | `src/watchdog/api/feishu_control.py:64-95 /实现证据; src/a_control_agent/api/deps.py:4-10 /实现证据; src/a_control_agent/risk/classifier.py:6-43 /实现证据` | — | — | 无验证、无入口 | 未落地 |

### 22. 最终交付物要求

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:937-948 / ## 22. 最终交付物要求` | 需要交付 A 服务、Watchdog 服务、集成代码、配置样例、部署说明、API 文档、测试与审计样例 | — | — | — | 无实现、无验证、无入口 | 未落地 |

## 约束 / 非执行性条款

> 这些条款属于 Out of Scope、非首版或供研发理解内容，不计入未落地矩阵。

| 来源 | 条款摘要 | 实现证据 | 验证证据 | 入口证据 | 缺口类型 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `openclaw-codex-watchdog-prd.md:74-84 / ### 3.2 Out of Scope` | 飞书机器人、OpenClaw 渠道插件本身的安装与接入 | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
| `openclaw-codex-watchdog-prd.md:74-84 / ### 3.2 Out of Scope` | A 机桌面 UI 层级的视觉监控或自动点击 | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
| `openclaw-codex-watchdog-prd.md:74-84 / ### 3.2 Out of Scope` | 完全无人值守地自动批准所有高风险命令 | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
| `openclaw-codex-watchdog-prd.md:74-84 / ### 3.2 Out of Scope` | git push / release / 发布流程自动化 | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
| `openclaw-codex-watchdog-prd.md:74-84 / ### 3.2 Out of Scope` | 远程桌面控制、通用 SSH 运维入口 | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
| `openclaw-codex-watchdog-prd.md:74-84 / ### 3.2 Out of Scope` | 对 OpenClaw 核心代码进行深度侵入式修改（优先通过外置服务集成） | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
| `openclaw-codex-watchdog-prd.md:917-925 / ## 20. 后续可扩展项（非首版）` | 多项目面板、差异化审批模板、语言栈分类器、更细粒度 compaction、Slack/Telegram/iMessage 复用、研发日报 | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
| `openclaw-codex-watchdog-prd.md:928-933 / ## 21. 参考约束（供研发理解，不要求照抄到代码）` | 协议层以 app-server 为核心、消费上游消息、内网优先、最小暴露面、审批与沙箱为系统级边界 | — | — | — | 非执行性条款（不计入未落地） | 非执行性条款（不计入未落地） |
