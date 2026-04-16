---
related_doc:
  - "docs/architecture/coverage-audit-closeout-execution-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/034-memory-hub-codex-critical/spec.md"
  - "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml"
---

# Missing Runtime Semantics And Action Surface — 功能规格说明

## 概述

`048-missing-runtime-semantics-and-action-surface` 是 `WI-047` 完成 AI-SDLC state reconciliation 之后的下一个正式执行 work item。它只消费 `matrix-owner-ledger.yaml` 中 owner=`WI-048` 的 22 条未落地矩阵行，目标是把“已经存在部分稳定骨架，但仍缺失运行时语义、动作映射和 fail-closed 边界”的条款收敛成可执行、可验证、可被后续入口批次消费的 canonical runtime surface。

048 的边界不是“把所有剩余需求一次做完”，而是只补三类能力：

- **runtime semantics**：把 PRD 要求的任务主状态、任务阶段、人工接管/人工决策、等待指引、打断循环、handoff/resume 等关键运行时语义冻结成 canonical contract；
- **action surface**：把 `continue / pause / resume / summarize / force_handoff / retry_with_conservative_path` 等动作映射到稳定 action codes、alias route 与 effect/result 语义；
- **fail-closed boundaries**：把审批风险边界、禁止事项和 `Memory Hub` 的最小 hot-path runtime consumption 固定为运行时纪律，而不是继续停留在 summary、模板或 advisory 文案层。

048 明确只消费已有基础：

- `WI-034` 已冻结 `Memory Hub` 的 bounded retrieval / packet input / fallback contract；
- `WI-035` 已冻结 `Brain / release gate` 的 runtime gate 语义；
- `WI-036` 已冻结 `Feishu primary control + OpenClaw compatibility-only` 边界；
- `WI-047` 已生成 row-level owner ledger，并把 22 条 runtime semantics/action surface 缺口唯一归属给 `WI-048`。

因此，048 不再做 AI-SDLC state repair，也不负责自然语言/飞书/OpenClaw 入口闭环；它交付的是后续 `WI-049` 和 `WI-050` 必须消费的 canonical runtime semantics baseline。

## 当前 owner 行范围

`WI-048` 当前负责的 22 条矩阵行固定为：

- **人工控制/接续/模板语义**
  - `matrix-row-0013` 持续无进展则升级飞书提醒并执行交接 / 续跑
  - `matrix-row-0015` 若任务目标不清晰，则在飞书中请求人工决策
  - `matrix-row-0017` 达到严重阈值时通知人工接管
  - `matrix-row-0043` 等待指引引导模板
  - `matrix-row-0044` 打断循环引导模板
  - `matrix-row-0046` `force_handoff` 缺失稳定动作代码映射
  - `matrix-row-0047` `pause` 缺失稳定动作代码映射
  - `matrix-row-0048` `summarize` 缺失稳定动作代码映射
  - `matrix-row-0049` `retry_with_conservative_path` 缺失稳定动作代码映射
- **审批边界/状态枚举/禁止事项**
  - `matrix-row-0024` `L0` 边界校验未证
  - `matrix-row-0025` `L1` 边界校验未证
  - `matrix-row-0026` `L2` 边界校验未证
  - `matrix-row-0027` `L3` 边界校验未证
  - `matrix-row-0034` 任务主状态枚举不一致
  - `matrix-row-0035` 任务阶段枚举不一致
  - `matrix-row-0058` 禁止事项未形成 fail-closed runtime boundary
- **Memory Hub / 连续性 / 最小生产语义**
  - `matrix-row-0105` 自动决策与生产化闭环缺口未补齐
  - `matrix-row-0111` 支撑远程压缩与跨会话交接的连续性
  - `matrix-row-0112` 项目事实/恢复案例/技能候选稳定提供给 `Brain`
  - `matrix-row-0113` `AI_AutoSDLC` 阶段感知模式保留但不纳入一期放行门槛
  - `matrix-row-0114` 四层记忆仅交付最小可用切片
  - `matrix-row-0115` 不能提升接续/自动决策/技能复用/解释性的功能不进入一期

若后续 `coverage-audit-matrix.md` 变更，必须重新运行 `scripts/reconcile_ai_sdlc_state.py` 并按新 owner ledger 重新冻结边界；048 不得手工追加或删减 owner 行。

补充边界说明：`matrix-row-0013 / 0015 / 0017` 中出现的“飞书提醒 / 飞书请求人工决策 / 飞书通知人工接管”在 048 只定义 canonical runtime semantic effect、reason code 与 receipt discipline，不负责任何 Feishu / OpenClaw / natural-language transport binding。对应渠道入口、路由与自然语言映射统一留给 `WI-049` 消费 048 交付的 runtime surface。

## 功能需求

- **FR-4801**：048 必须为任务主状态提供 canonical normalize contract，至少覆盖 `created / running / waiting_for_direction / waiting_for_approval / stuck / handoff_in_progress / resuming / paused / completed / failed`，并允许现有 `waiting_human / approval / done / coding` 等 legacy 实现态通过 compatibility mapping 收敛，而不是要求所有底层存储同时重写。
- **FR-4802**：048 必须为任务阶段提供 canonical normalize contract，至少覆盖 `planning / code_reading / editing_source / editing_tests / running_tests / debugging / summarizing / handoff`，并处理现有 `approval / recovery / done / coding` 等 legacy phase 的映射或兼容。
- **FR-4803**：048 必须为关键 steer 语义提供稳定模板与 reason code，至少覆盖 `soft steer`、`waiting-for-direction steer`、`break-loop steer`、`handoff summary prompt` 与严重阈值人工接管通知；模板不能继续散落为单一常量或临时 operator 文本。
- **FR-4804**：048 必须为 `continue / pause / resume / summarize / force_handoff / retry_with_conservative_path` 提供稳定 action code、canonical handler 与 alias route 映射；其中 `resume` 与 `force_handoff` 必须复用既有 recovery/handoff hot path，而不是绕过到新的旁路执行器。
- **FR-4805**：048 必须把“目标不清晰请求人工决策”“严重阈值人工接管”“持续无进展 handoff + resume”“break-loop conservative retry”等语义落为可测试的 runtime behavior，而不再停留在矩阵条款或 prompt 示例。
- **FR-4806**：048 必须把审批风险边界从 substring heuristic 扩展为显式 fail-closed policy boundary，至少覆盖 workspace / network / system / credential / destructive / publish 六类边界；未知或不完整输入默认升级到人工 gate。
- **FR-4807**：048 必须把“禁止桌面 OCR、任意命令执行、默认自动通过高风险命令、飞书逻辑与核心规则强耦合”等禁止事项落成 runtime enforcement 或 hard-block policy，而不是继续作为注释或 README 约束。
- **FR-4808**：048 必须把 `Memory Hub` 的 codex-critical 能力接到 runtime hot path：至少让 recovery/handoff/decision input 能消费项目事实、恢复案例、skill metadata 与 session archive refs；`Memory Hub` 不可用或冲突时必须通过 canonical events/facts 显式降级。
- **FR-4809**：048 必须继续保持 `Session Service + Goal Contract` 为唯一运行时真源；`Memory Hub` 只输出 advisory retrieval / packet inputs，`AI_AutoSDLC.stage/active_goal` 只允许作为 bootstrap context，不能覆盖 `Goal Contract.current_phase_goal`。
- **FR-4810**：048 不得负责飞书/OpenClaw/natural-language 到 canonical route 的正式入口闭环；它交付的 action surface 必须由 `WI-049` 作为入口层消费，而不是在 048 中直接补渠道接线。
- **FR-4811**：048 的实现必须保留 compatibility boundary：已有 raw task payload、legacy OpenClaw aliases、existing approval bridge 不得因为状态/动作扩展而 silently break；若需要迁移，必须通过 normalize layer 或 alias route 吸收。
- **FR-4812**：048 在进入实现前，必须经过 Anthropic Manager Expert 与 Hermes Agent Expert 的对抗评审，且 reviewed docs baseline、approval status、approved_by 必须落入 `.ai-sdlc/work-items/048-*`；其中 `docs_baseline_ref` 必须是对已评审 formal artifact set 的不可变 `SHA-256` 内容哈希，`T482` 开始前必须重算并验证未漂移。

### Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须是唯一且可重现的，禁止按“任意拼接方式”自由实现。048 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
   - `specs/048-missing-runtime-semantics-and-action-surface/spec.md`
   - `specs/048-missing-runtime-semantics-and-action-surface/plan.md`
   - `specs/048-missing-runtime-semantics-and-action-surface/tasks.md`
   - `specs/048-missing-runtime-semantics-and-action-surface/task-execution-log.md`
   - `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/execution-plan.yaml`
   - `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
6. 写入 `docs_baseline_ref` 与后续 `T482` 校验必须使用同一配方；若任一文件内容、顺序或路径标签变化，视为 baseline 漂移，必须回到 `T481` 重新评审。

## Canonical 状态转移契约

048 冻结的是 runtime semantic surface，而不是只给出状态词汇表。实现与测试必须同时遵守以下 canonical transition contract；任何未列入的状态/动作组合都视为非法，不得通过“自动修正”“隐式放行”或 ad hoc route 偷渡。

### 运行时事件驱动的主状态转移

- `created -> running`：任务首次进入执行。
- `running -> waiting_for_direction`：目标不清晰、上下文不足或需要人工决策。
- `running -> waiting_for_approval`：命中审批边界，需要人工 gate。
- `running -> stuck`：出现 break-loop、连续失败或无法前进的运行时阻塞。
- `running|stuck -> handoff_in_progress`：持续无进展、严重阈值升级、或需要人工接管。
- `handoff_in_progress -> resuming`：handoff packet 被接受并进入恢复。
- `resuming -> running`：recovery hot path 完成，任务重新恢复执行。
- `any non-terminal -> paused`：显式暂停成功后进入暂停态。
- `running|stuck|resuming -> completed|failed`：只允许由实际执行结果驱动，不能由人工动作直接伪造终态。

### Canonical action to status/effect contract

| Action | Allowed source states | Required guard | Canonical target / effect |
| --- | --- | --- | --- |
| `continue` | `created`, `running`, `waiting_for_direction`, `waiting_for_approval` | 若源状态为 `waiting_for_direction`，必须携带有效人工指引；若源状态为 `waiting_for_approval`，必须已有批准回执 | `created -> running`；`running -> running`（幂等继续）；`waiting_for_direction -> running`；`waiting_for_approval -> running` |
| `pause` | `created`, `running`, `waiting_for_direction`, `waiting_for_approval`, `stuck`, `resuming` | 无额外 guard，但必须生成 pause receipt | `-> paused` |
| `resume` | `paused`, `handoff_in_progress` | 必须复用既有 recovery/handoff hot path，且存在可消费的 continuation context | `-> resuming`，随后仅在 recovery 成功后 `resuming -> running` |
| `summarize` | 所有状态 | 只读动作，不得改变主状态 | 生成 summary / handoff artifact，主状态保持不变 |
| `force_handoff` | `running`, `waiting_for_direction`, `waiting_for_approval`, `stuck`, `paused` | 必须生成 handoff summary/packet，并走既有 handoff path | `-> handoff_in_progress` |
| `retry_with_conservative_path` | `running`, `stuck` | 必须携带或派生 break-loop / conservative-retry reason | `-> running`，并记录 conservative retry effect / receipt |

### 非法转移与拒绝语义

- `continue` 不得绕过审批或人工决策 gate；缺少批准回执或人工指引时，必须拒绝并保持原状态。
- `resume` 不得直接从 `waiting_for_direction`、`waiting_for_approval`、`running` 或终态进入 `resuming`。
- `force_handoff` 与 `pause` 不得伪造 `completed` 或 `failed`。
- 终态 `completed` / `failed` 上只允许 `summarize` 这类只读语义；任何变更性动作都必须被拒绝。
- 非法状态/动作组合必须返回 canonical rejected receipt（例如 `rejected_invalid_state` 或等价 canonical code），记录 attempted action、source state、guard failure reason，并保证主状态不变。

### Memory Hub precedence contract

- `Session Service + Goal Contract` 永远优先于 `Memory Hub`。
- `Memory Hub` 返回的 project facts / recovery cases / skill metadata / archive refs 只允许作为 advisory input，不得覆盖 `current_phase_goal`、canonical task status 或 approval decision。
- 当 `Memory Hub` 不可用时，runtime 必须继续走 session-only path，并显式记录 `memory_unavailable_degraded`（或等价 canonical event/fact）。
- 当 `Memory Hub` 与 `Session Service + Goal Contract` 冲突时，runtime 必须继续以 session truth 为准，显式记录 `memory_conflict_detected`（或等价 canonical event/fact），并保留冲突证据用于审计；冲突本身不得改变决策路径。

## 用户故事

### 用户故事 1：维护者需要稳定的运行时状态和动作语义

作为维护者，我需要一套稳定的 canonical task state / phase / action contract，这样后续入口层和验证层才能消费同一套语义，而不是继续在 `waiting_human`、`approval`、`done`、`coding` 与 PRD 枚举之间来回翻译。

场景 1：任务进入审批等待时，系统对外应该表现为 `waiting_for_approval`，但底层兼容层仍可暂时保留 legacy raw value。048 完成后，runtime 和 stable read surface 必须都能输出 canonical status，而不会要求一次性重写所有旧存储。

场景 2：用户请求 `pause` 或 `force_handoff` 时，系统必须走稳定 action code 和 receipt/effect 语义，而不是靠 operator message 或 ad hoc route 触发。

### 用户故事 2：审批和禁止事项需要 fail-closed，而不是启发式碰运气

作为审批/控制平面的维护者，我需要明确知道哪些操作必须人工 gate，哪些绝对不允许自动通过，否则 `L0/L1/L2/L3` 只会停留在启发式字符串匹配层。

场景 1：请求含网络访问、工作区外访问、凭据、系统级副作用或发布操作时，即便命令文本没有命中已有 marker，也必须升级到人工 gate，而不是默认为 `L0`。

场景 2：任何“自动通过高风险命令”“桌面 OCR”“绕过核心规则”的企图，都必须 fail closed，并留下可审计原因。

### 用户故事 3：长时连续性需要真正消费 Memory Hub，而不是只停留在 contract

作为长时自动开发链路的维护者，我需要 recovery/handoff/decision input 真正消费项目事实、恢复案例和技能候选，否则 `remote compact` 和新线程续跑场景仍然没有最小生产语义。

场景 1：会话因 `remote compact` 中断后，系统应能从 session archive / project facts / recovery cases 组装最小 continuation packet，而不是只留下 handoff 文件。

场景 2：`Memory Hub` 不可用或与 Session facts 冲突时，系统必须显式退化并记录 canonical event，而不是静默忽略。

## 非目标

- 不在 048 中补飞书/OpenClaw/natural-language 主入口。
- 不在 048 中完成性能、重启、安全、可靠性、测试报告或最终交付物验收。
- 不在 048 中把 `Memory Hub` 升级成新的 orchestrator 或第二真相源。
- 不在 048 中把 backlog 测试强化、专项高耦合验证并入当前批次。
- 不在 048 中回退或重写 `WI-034 / WI-035 / WI-036 / WI-047` 已冻结的 formal truth。
