---
related_doc:
  - "docs/architecture/coverage-audit-closeout-execution-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml"
  - "specs/048-missing-runtime-semantics-and-action-surface/spec.md"
---

# Feishu And Feishu Entrypoint Closure — 功能规格说明

## 概述

`049-feishu-entrypoint-closure` 是 `WI-048` 完成 runtime semantics baseline 之后的正式后续 work item。它只消费 `matrix-owner-ledger.yaml` 中 owner=`WI-049` 的 92 条矩阵行，目标是把“已有 canonical route 与 runtime semantics，但仍缺正式入口、渠道接线、自然语言语义映射与主链路验证”的缺口收敛成稳定的 entry surface。

049 的边界不是重新定义产品语义，而是收口三类能力：

- **Feishu primary entrypoint**：把 Feishu 从“只覆盖 approval response / bootstrap 的局部入口”扩成正式主链路入口，可查询进展、解释阻塞、处理审批与触发 canonical control action；
- **Feishu compatibility entrypoint**：让 Feishu 只作为兼容入口消费 048 冻结的 canonical read/action surface，不再自行发明语义；
- **natural-language mapping**：把用户在 Feishu / Feishu 中输入的自然语言短指令稳定映射到 canonical query / action route，而不是继续停留在示例或 operator 约定。

049 明确只消费已有基础：

- `WI-047` 已冻结 owner ledger，明确 92 条 row-level owner 属于 `WI-049`；
- `WI-048` 已冻结 canonical task status / phase、stable action surface、fail-closed boundary 与 `Memory Hub` precedence contract；
- `WI-036` 已冻结 “Feishu primary control plane，Feishu compatibility-only” 的总体迁移边界。

因此，049 不再修改 048 已冻结的 runtime semantics，也不负责性能、重启、安全、最终验收或 backlog test hardening；它交付的是后续 `WI-050` 和 `WI-051` 必须消费的正式入口 surface。

## 当前 owner 行范围

`WI-049` 当前负责 `matrix-owner-ledger.yaml` 中全部 owner=`WI-049` 的 92 条矩阵行。它们不是新的功能真相，而是 048 运行时能力的入口闭环与渠道消费闭环。代表性条目包括：

- **Feishu 进展 / 审批 / 控制入口**
  - `matrix-row-0001` 任务进展可查询
  - `matrix-row-0006` 飞书中随时查询指定项目任务进展，响应时间小于 5 秒（049 只负责入口，不负责 <5 秒 基准）
  - `matrix-row-0010` `L0/L1/L2/L3` 审批模型通过飞书入口对外呈现
  - `matrix-row-0012` 飞书查询返回阶段、摘要、文件、阻塞点、审批状态、上下文压力
  - `matrix-row-0307` `L2`：中风险飞书提醒人工审批
  - `matrix-row-0937` 用户在飞书输入“现在进展”可返回当前任务摘要
  - `matrix-row-0979` 在出现 `L2` 审批请求时，系统通过飞书提醒人工审批
- **自然语言语义映射**
  - `matrix-row-0014` 目标明确时自动走最小风险路径继续执行
  - `matrix-row-0016` 同类错误连续出现时自动打断循环并选择最小变更方案
  - `matrix-row-0714` 飞书侧建议命令语义
  - `matrix-row-0699` Feishu 侧把飞书消息转成 Watchdog 接口调用并做项目路由
- **Feishu compatibility-only 入口**
  - `matrix-row-0699` Feishu 侧项目路由与调用映射
  - `matrix-row-1329` 飞书成为唯一主控制面，Feishu 只保留兼容读写
- **正式入口集成与 release gate 消费**
  - `matrix-row-0909` 创建任务、审批、恢复、A 不可达、飞书语义映射都要做集成测试
  - `matrix-row-1343` 至少一条 `Feishu -> Goal Contract -> Brain -> ...` 主链路可重复通关且产出 `release_gate_report`
  - `matrix-row-1399` 后续入口必须复用共享加载/证据包契约
  - `matrix-row-1441` 刷新/重建/夹具再生成只有一个正式命令入口
- **禁止事项在入口侧的消费约束**
  - `matrix-row-0811` 禁止桌面 `OCR`、任意命令执行、默认自动通过高风险命令、飞书逻辑与核心规则强耦合

若后续 `coverage-audit-matrix.md` 变更，必须重新运行 `scripts/reconcile_ai_sdlc_state.py` 并按新 owner ledger 重新冻结边界；049 不得手工追加或删减 owner 行。

补充边界说明：`matrix-row-0013 / 0015 / 0017` 这类“无实现、无验证、无入口”的条目仍然属于 `WI-048` 的语义实现范围。049 只负责把 048 已交付的 semantic effect、reason code 与 canonical action surface 暴露给 Feishu / Feishu / natural-language 入口消费。

## 功能需求

- **FR-4901**：049 必须提供正式 Feishu 主入口，至少覆盖 `get_progress / get_session / explain_blocker / why_stuck / list_pending_approvals / continue / pause / resume / summarize / force_handoff / retry_with_conservative_path / goal_contract_bootstrap` 的可达 surface。
- **FR-4902**：049 必须让 Feishu 主入口只消费 `WI-048` 已冻结的 canonical query / action route，不得重新解释状态、动作或审批真相。
- **FR-4903**：049 必须把自然语言短指令稳定映射到 canonical intent，至少覆盖中文/英文的最小命令集：`现在进展`、`任务状态`、`为什么卡住`、`继续`、`暂停`、`恢复`、`总结`、`转人工`、`保守重试`、`审批列表`。
- **FR-4904**：049 必须让 Feishu compatibility entrypoint 复用共享的 intent catalog / natural-language mapping / project routing，而不是继续在 adapter 或 examples 中散落 ad hoc 逻辑。
- **FR-4905**：049 必须支持稳定项目路由，至少允许通过 `project_id`、`native_thread_id` 或与当前 session 绑定的 entry context 解析到 canonical target session。
- **FR-4906**：049 必须保持 Feishu 为 primary control plane，Feishu 只保留 compatibility-only 读写入口；任何新增主链路能力都不能先落在 Feishu 独占 surface 上。
- **FR-4907**：049 必须为 Feishu / Feishu 入口加上受控入口纪律：继续复用 token 鉴权、canonical approval / receipt / audit / session event 写屏障，不允许入口层绕过审计。
- **FR-4908**：049 必须把入口层“查询进展 / 解释阻塞 / 提交审批响应 / 触发恢复或控制动作 / Goal Contract bootstrap”都落到可测试的 live route 或主链路消费 surface，不能用 `examples/`、summary、兼容壳或 README 文字充当入口证据。
- **FR-4909**：049 不得改变 `Memory Hub` precedence contract；入口层只允许把 query / goal_message / action request 转成 canonical runtime consumption，不得把 `Memory Hub` 提升成第二真相源。
- **FR-4910**：049 不得负责 `<5 秒` 性能基准、重启恢复、安全验收、最终交付物或专项高耦合 hardening；这些仍留给 `WI-050` / `WI-051`。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。049 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
   - `specs/049-feishu-entrypoint-closure/spec.md`
   - `specs/049-feishu-entrypoint-closure/plan.md`
   - `specs/049-feishu-entrypoint-closure/tasks.md`
   - `specs/049-feishu-entrypoint-closure/task-execution-log.md`
   - `.ai-sdlc/work-items/049-feishu-entrypoint-closure/execution-plan.yaml`
   - `.ai-sdlc/work-items/049-feishu-entrypoint-closure/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。

## 用户故事

### 用户故事 1：操作者需要在飞书里直接查询和控制任务

作为操作者，我需要在飞书里直接输入“现在进展”“为什么卡住”“暂停”“恢复”等命令，就能命中稳定的 Watchdog canonical route，而不是再通过人工翻译或临时脚本找项目状态。

场景 1：飞书输入“现在进展”后，系统返回当前任务阶段、摘要、文件、阻塞点、审批状态、上下文压力。

场景 2：飞书输入“暂停”或“转人工”后，系统调用 048 已冻结的 canonical action surface，并返回稳定 receipt / effect。

### 用户故事 2：Feishu 仍需要作为兼容层消费统一入口语义

作为维护者，我需要 Feishu 继续可用，但只以 compatibility-only 身份消费共享 intent catalog、project routing 和 canonical route，这样不会再次把 Feishu 变回主链路。

场景 1：Feishu 收到“继续 / 恢复 / 总结 / 审批列表”等短指令时，走与 Feishu 相同的 canonical intent 映射。

场景 2：Feishu 兼容入口的项目路由、native thread 解析与 action receipt 查询使用统一 contract，而不是散落在 examples 或单测替身里。

### 用户故事 3：入口层不能偷偷改变 048 已冻结的真相

作为系统维护者，我需要 Feishu / Feishu / natural-language 入口只做路由和消费，不重新发明任务状态、审批真相或 Memory precedence，否则 048 的 runtime baseline 会再次漂移。

场景 1：自然语言“恢复”只映射到 `resume_session` 或 recovery hot path，不允许新增旁路执行器。

场景 2：入口层触发控制动作后，仍然通过 canonical approval / receipt / session event 写屏障留下审计证据。

## 非目标

- 不在 049 中重定义 048 已冻结的 runtime semantics、action surface 或 Memory precedence contract。
- 不在 049 中完成 `<5 秒` 性能基准、重启恢复、安全/可靠性验收或最终测试报告。
- 不在 049 中把 Feishu 恢复成主控制面。
- 不在 049 中合并 backlog 高耦合 hardening。
