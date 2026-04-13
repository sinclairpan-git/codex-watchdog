---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/036-feishu-control-plane-and-openclaw-retirement/spec.md"
---

# 实施计划：037-autonomy-golden-path-and-release-gate-e2e

## 目标

把一期自治主链正式冻结为可重复、可审计、可阻断放行的 e2e release blocker，并把 `release_gate_report`、runbook/script、midstate recovery 与 child session continuation 都纳入同一条正式通关链路。

## 架构摘要

- **One release-blocking golden path**：037 不做多条演示链路；它只固定一条一期正式主链，并把其必要分支场景收口为 recovery/override/degrade 断言。
- **Reuse canonical contracts, do not invent new truth**：golden path 只消费 030-036 已冻结的 `Session Service`、projection、Goal Contract、Recovery Transaction、Brain、Release Gate 与 Feishu control contract，不新增第二状态机。
- **Evidence before auto-execution**：low-risk auto-decision 只能发生在 `certification_packet_corpus + shadow_decision_ledger + release_gate_report + runbook/script artifacts` 全部可验证时；其中 `tool_schema_hash` 与其他 runtime contract drift 轴一样必须被硬校验；否则 runtime 必须自动降级。
- **Recovery stays in the same chain**：worker crash、claim timeout、notification failure、stale interaction 与 `remote compact` child continuation 不是旁路补丁，而是 golden path 内建的受治理中间态。
- **Hermetic e2e is the release gate**：e2e 测试必须可本地重复执行、可审计、无外网依赖，并被明确标记为一期 release blocker。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Golden path e2e | `tests/e2e/test_watchdog_autonomy_golden_path.py` | 固定一期单一主链从 Feishu DM 到 completion/replay/metrics 的 happy path，并断言全链 canonical evidence |
| Midstate recovery e2e | `tests/e2e/test_watchdog_midstate_recovery.py` | 固定 worker crash、claim timeout、notification failure、supersede/stale interaction、人工 override 与 child session continuation 的恢复 contract |
| Release gate e2e | `tests/e2e/test_watchdog_release_gate_e2e.py` | 固定 `certification_packet_corpus + shadow_decision_ledger + release_gate_report + runbook/script artifacts` 到 low-risk auto-decision 的资格门禁与 fail-closed 行为 |
| Release gate runtime | `src/watchdog/services/brain/release_gate.py`, `src/watchdog/services/brain/release_gate_evidence.py` | 继续承担 report/evidence 解析、hash drift 校验、artifact/runbook 元数据校验与 degrade reason 分类 |
| Control-plane / session glue | `src/watchdog/services/feishu_control/service.py`, `src/watchdog/services/session_service/service.py` | 把 interaction context、approval/read refs、command lease、recovery tx、child continuation 与 completion evidence 接到同一条 canonical 主链 |
| Ops / release blocker surfacing | `tests/test_watchdog_ops.py` | 验证一期 release blocker 所需的 ops/read-side 字段与报告阻断语义可见、稳定且不回退 |

## 边界纪律

- 037 不得为 e2e 单独定义测试专用真相层或临时旁路 API。
- 037 不得依赖手工 DB patch、手工补 event、手工替换 `release_gate_report`、手工重置 interaction context 或手工跳过审批来让测试通过。
- 037 不得回退到 OpenClaw 主控制面、policy-only auto execute 或手写 report 直通 runtime。
- 037 不得把 release gate 变成“文档写着要有”的软约束；必须在 runtime 和 e2e 中硬阻断。
- 037 不得把 flaky 或人工演示视作一期通关替代物；e2e 本身就是 release blocker。

## 依赖顺序

1. **先冻结 formal docs 与 037 work item 元数据**
   - 把总实施计划中的 `Task 8` 正式拆成 canonical execution work item；
   - 明确当前仓库已经具备 030-036 的 contract，但还没有一期正式 e2e release blocker。
2. **再写失败测试锁定一期主链与恢复场景**
   - 先让 e2e 明确失败于 golden path 缺口、midstate recovery 缺口或 release gate 硬阻断缺口；
   - 先锁定“无手工补状态即可复跑”的正式口径。
3. **再补跨模块 glue，把主链真正串通**
   - 在 release gate / Feishu control / session service 中补齐 canonical refs、recovery continuation、completion evidence 与 report 归档摘要；
   - 保证 recovery、override、child continuation 仍留在同一条主链中。
4. **再收口 release blocker 语义**
   - 固定 runbook/script、样本冻结窗口、`label_manifest`、报告归档与 input hash drift 都是 hard blocker；
   - 固定 e2e/ops 对 release gate fail-closed 的观察面。
5. **最后运行验证并更新 handoff**
   - 让 `task-execution-log.md` 与 `.ai-sdlc` 元数据准确反映一期已通关或仍阻断在哪个 gating point。

## 分阶段计划

### Phase 1：冻结 037 formal docs、任务分解与执行元数据

交付内容：

- `specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md`
- `specs/037-autonomy-golden-path-and-release-gate-e2e/plan.md`
- `specs/037-autonomy-golden-path-and-release-gate-e2e/tasks.md`
- `specs/037-autonomy-golden-path-and-release-gate-e2e/task-execution-log.md`
- `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/*`

关键原则：

- 先把 037 收紧为一期 release-blocking golden path，而不是泛化的 e2e 测试集合；
- 明确它只消费 030-036 已冻结的 contract。

### Phase 2：写失败测试锁定 golden path、midstate recovery 与 release gate e2e blocker

交付内容：

- `tests/e2e/test_watchdog_autonomy_golden_path.py`
- `tests/e2e/test_watchdog_midstate_recovery.py`
- `tests/e2e/test_watchdog_release_gate_e2e.py`

关键原则：

- 红测优先锁定一条正式主链，而不是多个半成品场景；
- 红测优先锁定 worker crash、claim timeout、notification failure、supersede/stale interaction、人工 override 与 child continuation；
- 红测优先锁定没有有效 `release_gate_report` 或 formal artifacts 时必须 fail closed。

### Phase 3：补齐跨模块 golden path glue 与恢复接续

交付内容：

- `src/watchdog/services/feishu_control/service.py`
- `src/watchdog/services/session_service/service.py`
- `src/watchdog/services/brain/release_gate.py`
- `src/watchdog/services/brain/release_gate_evidence.py`

关键原则：

- 只补主链缺失的 canonical refs、recovery continuation、completion evidence 与 artifact summary；
- 不新造真相层，不把恢复逻辑散回 handler/store 分支。

### Phase 4：收口 release blocker 语义、ops surfacing 与重复性验证

交付内容：

- `tests/e2e/test_watchdog_autonomy_golden_path.py`
- `tests/e2e/test_watchdog_midstate_recovery.py`
- `tests/e2e/test_watchdog_release_gate_e2e.py`
- `tests/test_watchdog_ops.py`
- `src/watchdog/services/brain/release_gate.py`
- `src/watchdog/services/brain/release_gate_evidence.py`

关键原则：

- `release_gate_report`、runbook/script、`label_manifest`、样本窗口、artifact archive 与 drift 校验必须全部进入 hard blocker；
- ops/read-side 必须能看见当前阻断原因，而不是只在 e2e 内部知道失败。

### Phase 5：运行验证并更新 handoff 摘要

交付内容：

- `specs/037-autonomy-golden-path-and-release-gate-e2e/task-execution-log.md`
- `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/execution-plan.yaml`
- `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/runtime.yaml`
- `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/resume-pack.yaml`
- `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md`

关键原则：

- handoff 必须指出一期是否已经具备正式通关标准，或者具体阻断在何处；
- 后续工作只能消费 037 已冻结的 release blocker contract，不能再把通关标准降回口头流程。

## 测试计划

- `tests/e2e/test_watchdog_autonomy_golden_path.py`
  - 冻结 `Feishu DM -> Goal Contract -> Brain decision -> Session write barrier -> command lease -> execution / approval -> completion -> replay / metrics` 主链
  - 断言 `goal_contract_version`、`decision_trace_ref`、`approval_read_ref`、`release_gate_report`、completion evidence 全部来自 canonical truth
  - 断言重复执行不依赖手工补状态
- `tests/e2e/test_watchdog_midstate_recovery.py`
  - 覆盖 worker crash、claim timeout、notification failure、superseded context、stale interaction、人工 override 与 `remote compact` child continuation
  - 断言恢复通过 canonical recovery / interaction contract 完成，而不是靠手工补丁
- `tests/e2e/test_watchdog_release_gate_e2e.py`
  - 覆盖 `certification_packet_corpus + shadow_decision_ledger + release_gate_report` 到 low-risk auto-decision 的资格门禁
  - 覆盖 runbook/script、样本冻结窗口、`label_manifest`、`generated_by`、`approved_by`、`artifact_ref` 缺失时 fail closed
  - 覆盖 `tool_schema_hash` drift、report drift、TTL 过期、input hash 不一致、approval stale、memory conflict 时自动降级
- `tests/test_watchdog_ops.py`
  - 覆盖 release blocker 所需的阻断原因、report 元数据和恢复可观测性不回退

## 主要风险与应对

### 风险 1：e2e 只是演示 happy path，无法代表正式放行标准

应对：

- 只保留一条正式一期主链；
- 把 fail-closed 和 recovery 断言并入同一批 release-blocking e2e。

### 风险 2：中间态恢复仍需人工补状态

应对：

- e2e 强制覆盖 worker crash、claim timeout、notification failure、supersede/stale、child continuation；
- 任一场景若依赖手工改状态，视为未通关。

### 风险 3：release gate 报告存在，但 runtime 没有真正阻断

应对：

- e2e 与 ops 同时断言 `tool_schema_hash` drift、report drift / 过期 / 缺失 / artifact 缺口时 fail closed；
- 低风险自动执行必须以当前 input hash 与 formal artifacts 为前提。

### 风险 4：为追求 e2e 通过而回退到旁路逻辑

应对：

- 037 只允许补 glue，不允许引入新的 bypass；
- 所有关键 refs 都必须能回到 Session truth、DecisionTrace、Recovery Tx 与 Release Gate artifacts。

## 验收口径

只有当以下条件同时满足，037 才算完成：

1. 一期存在且只存在一条正式、可重复、可审计的自治主链路；
2. worker crash、claim timeout、notification failure、supersede/stale interaction、人工 override 与 child continuation 都能在不手工补状态的前提下回到主链；
3. `release_gate_report`、runbook/script、`label_manifest`、样本冻结窗口与 artifact archive 都已成为 low-risk auto-decision 的硬阻断输入；
4. report 缺失、漂移、过期、approval stale、memory conflict 或 artifact 缺口时，runtime 与 e2e 都会 fail closed；
5. `tests/e2e/test_watchdog_autonomy_golden_path.py`、`tests/e2e/test_watchdog_midstate_recovery.py` 与 `tests/e2e/test_watchdog_release_gate_e2e.py` 已成为正式 release blocker；
6. 后续 handoff 不再依赖人工演示、手工补状态或口头放行说明。
