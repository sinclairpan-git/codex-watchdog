---
related_doc:
  - "docs/architecture/coverage-audit-closeout-execution-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/034-memory-hub-codex-critical/spec.md"
  - "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml"
---

# 实施计划：048-missing-runtime-semantics-and-action-surface

## 目标

把 `WI-048` owner 行收敛为一套稳定、可验证、可被 `WI-049` 消费的 runtime semantics baseline：canonical task status/phase、steer template registry、stable action surface、fail-closed approval boundary，以及 `Memory Hub` 的最小 hot-path runtime consumption。

## 架构摘要

- **Normalize, do not rewrite blindly**：优先通过 canonical normalize layer 吸收 legacy task status / phase / approval waiting 值，而不是一次性重写所有现有存储和回放数据。
- **Action surface before entry surface**：048 只交付 action code / handler / receipt / effect / alias route，不做 Feishu/Feishu/natural-language 的入口闭环；后续入口层只能消费 048 冻结的 runtime semantics。
- **Memory Hub stays advisory**：`Memory Hub` 只增强 recovery / decision input 的 continuity packet，不能成为真相源；不可用时必须显式 degrade，冲突时必须继续以 `Session Service + Goal Contract` 为准并写入 canonical conflict event。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
| --- | --- | --- |
| Formal docs / task plan | `specs/048-missing-runtime-semantics-and-action-surface/*` | 冻结 048 owner 行范围、任务拆解、执行日志与 handoff |
| Runtime state normalization | `src/watchdog/services/session_spine/task_state.py`、`src/a_control_agent/storage/tasks_store.py`、`src/a_control_agent/services/codex/client.py` | 收敛 canonical task status / phase，吸收 legacy raw values |
| Stable steer templates | `src/watchdog/services/action_executor/steer.py` | 冻结 soft / waiting-for-direction / break-loop / handoff summary 等模板与 reason code |
| Stable action handlers | `src/watchdog/contracts/session_spine/enums.py`、`src/watchdog/services/session_spine/actions.py`、`src/watchdog/api/session_spine_actions.py` | 扩展 canonical action code、effect、alias route 与 receipt 语义 |
| Recovery / takeover semantics | `src/watchdog/services/session_spine/recovery.py`、`src/watchdog/services/session_spine/orchestrator.py` | 复用既有 recovery path 实现 `force_handoff` / `resume` / severe-threshold takeover |
| Approval boundary / risk fail-closed | `src/a_control_agent/risk/classifier.py`、`src/a_control_agent/services/codex/app_server_bridge.py` | 把 workspace/network/system/credential/destructive/publish 边界收口为显式 risk contract |
| Memory Hub hot-path runtime consumption | `src/watchdog/services/memory_hub/service.py`、`src/watchdog/services/brain/service.py`、`src/watchdog/services/session_spine/recovery.py` | 让 recovery/decision input 真正消费 project facts / recovery cases / skills / archive refs，并显式 degrade |
| Contract / regression tests | `tests/test_watchdog_runtime_semantics.py`、`tests/test_watchdog_steer.py`、`tests/test_watchdog_memory_hub.py`、`tests/test_watchdog_memory_degradation.py`、`tests/test_a_control_agent.py`、`tests/test_watchdog_action_execution.py` | 锁定 048 的状态/动作/风险/Memory Hub 运行时语义 |

## 边界纪律

- 048 不得把飞书/Feishu/natural-language 主入口并入当前 work item。
- `matrix-row-0013 / 0015 / 0017` 在 048 只交付 semantic effect、reason code 与 receipt discipline；任何 Feishu / route binding 统一留给 `WI-049`。
- 048 不得把 `Memory Hub` 升级成新的 runtime truth source；`Session Service + Goal Contract` 仍是唯一真相源。
- 048 不得靠 README、summary、example 或 prompt 文案伪装“动作已落地”；必须有 canonical action/effect/test 证据。
- 048 不得要求现有 raw task payload 一次性全部迁移；必须通过 normalize/compatibility layer 吸收。
- 048 不得回退到 substring-only risk heuristic；未知边界输入默认 fail closed。
- 048 不得关闭 `WI-049` 的入口条款或 `WI-050` 的验证/NFR 条款。

## 测试计划

- `tests/test_watchdog_runtime_semantics.py`
- `tests/test_watchdog_action_execution.py`
- `tests/test_watchdog_steer.py`
- `tests/test_a_control_agent.py`
- `tests/test_watchdog_memory_hub.py`
- `tests/test_watchdog_memory_degradation.py`

## Review Gate

`T481` 完成后才能进入实现。最小机器门禁为：

- `docs_baseline_ref` 必须按 `spec.md` 中冻结的 hash recipe 生成：固定 artifact 路径顺序、`LF` 归一化、缺失末尾换行补单一 `LF`、并以 `<<<PATH:...>>>` 标签串联为单一 UTF-8 payload 后计算 `SHA-256`
- `runtime.yaml` 与 `resume-pack.yaml` 中存在一致的 `docs_baseline_ref`
- `docs_baseline_at` 已记录 048 docs 对抗评审完成时间
- `review_approval_status == approved`
- `review_approved_by` 至少包含 `Anthropic Manager Expert` 与 `Hermes Agent Expert`
- `current_branch` 已 pin 到 `codex/048-missing-runtime-semantics-and-action-surface`
- `checkpoint.yml.feature.id` 已切到 `048-missing-runtime-semantics-and-action-surface`
- `project-state.yaml.next_work_item_seq` 已更新为 `49`
- `T482` 开始前必须重算 reviewed artifact set 哈希并与 `docs_baseline_ref` 一致；若文档漂移，必须回退到 `T481`

缺任一项，都不得开始 `T482`

## 交付物

- `specs/048-missing-runtime-semantics-and-action-surface/spec.md`
- `specs/048-missing-runtime-semantics-and-action-surface/plan.md`
- `specs/048-missing-runtime-semantics-and-action-surface/tasks.md`
- `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/*`
- 048 冻结后的 canonical runtime semantics / action surface / risk boundary / memory hot-path tests
