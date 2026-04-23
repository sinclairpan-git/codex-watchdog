# 任务分解：047-ai-sdlc-state-reconciliation-and-canonical-gate-repair

> 对应规格：`specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/spec.md`
>
> 对应计划：`specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/plan.md`

## Task 47.1 冻结 047 formal docs 与 AI-SDLC reconciliation 边界

- **任务编号**：T471
- **状态**：已完成（2026-04-16）
- **目标**：把 coverage audit closeout 的第一执行入口正式冻结为 AI-SDLC state reconciliation and canonical gate repair。
- **文件**：
  - `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/spec.md`
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/plan.md`
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/tasks.md`
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/task-execution-log.md`
  - `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 047 只做 state truth、missing mirror、owner ledger 与 framework gate 修复；
  2. 已明确 `next_work_item_seq = max(specs, work-items) + 1` 的单一算法；
  3. 已明确缺失镜像 inventory：`006, 010-021, 024-029`；
  4. Anthropic Manager 专家与 Hermes Agent 专家复核后无 blocking/P1；
  5. `runtime.yaml` 与 `resume-pack.yaml` 已写入 reviewed docs baseline：`docs_baseline_ref`、`docs_baseline_at`、`review_approval_status=approved`、`review_approved_by`；
  6. `current_branch` 已 pin 到当前 canonical WI，而不是旧 work item branch。
- **验证**：
  - 人工审阅 formal docs 与 `.ai-sdlc/work-items/047-*` 基线一致
- **完成情况**：
  1. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/047-*` 基线；
  2. 已把当前 work item pin 到 `codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair`；
  3. Anthropic Manager 专家与 Hermes Agent 专家复核均无 blocking/P1/P2；
  4. reviewed docs baseline、approval status 与 approved_by 已原子写入 `runtime.yaml` 与 `resume-pack.yaml`。

## Task 47.2 写失败测试锁定 reconciliation inventory、sequence rule 与 owner ledger contract

- **任务编号**：T472
- **状态**：已完成（2026-04-16）
- **目标**：用失败测试先锁定 047 的 deterministic 规则，而不是依赖手工口径。
- **文件**：
  - `src/watchdog/validation/ai_sdlc_reconciliation.py`
  - `tests/test_ai_sdlc_reconciliation.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `next_work_item_seq` 必须按并集最大编号计算；
  2. 覆盖缺失 `.ai-sdlc/work-items` 镜像清单必须稳定识别 `006, 010-021, 024-029`；
  3. 覆盖 owner tie-break 规则必须按 `047 -> 048 -> 049 -> 050 -> 051` 唯一归属；
  4. 覆盖 stale top-level pointer 必须被识别，而不能默默通过；
  5. 覆盖 reviewed docs baseline / approval status 未落档时不得进入实现；
  6. 覆盖 `runtime.yaml` / `execution-plan.yaml` / `resume-pack.yaml` / `latest-summary.md` 的一致性不变量；
  7. 覆盖 owner ledger 必须对剩余矩阵行 1:1 覆盖、标识唯一、无重复归属。
- **验证**：
  - `uv run pytest -q tests/test_ai_sdlc_reconciliation.py`
- **完成情况**：
  1. 已新增 `tests/test_ai_sdlc_reconciliation.py`，覆盖 inventory、stale pointer、review gate、lifecycle drift、owner tie-break 与矩阵 parser；
  2. 已新增 `src/watchdog/validation/ai_sdlc_reconciliation.py`，并完成红绿循环；
  3. `uv run pytest -q tests/test_ai_sdlc_reconciliation.py` 已通过（`5 passed in 0.02s`）。

## Task 47.3 实现最小 reconciliation helper、artifact generator 与 state repair

- **任务编号**：T473
- **状态**：已完成（2026-04-16）
- **目标**：让 047 的 state reconciliation 从文档规则变成可执行工具和正式产物。
- **文件**：
  - `src/watchdog/validation/ai_sdlc_reconciliation.py`
  - `scripts/reconcile_ai_sdlc_state.py`
  - `tests/test_ai_sdlc_reconciliation.py`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
  - `.ai-sdlc/work-items/{006,010-021,024-029}/*`
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/reconciliation-inventory.yaml`
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml`
- **可并行**：否
- **验收标准**：
  1. shared reconciliation helper 已能生成 deterministic inventory、缺失镜像清单与 `next_work_item_seq`；
  2. 已生成 reconciliation inventory 与 row-level owner ledger；
  3. 缺失 `.ai-sdlc/work-items` 镜像已补齐最小 metadata；
  4. 顶层 checkpoint / project-state 已收敛到新的 active WI 与 next seq；
  5. owner ledger 已证明对剩余矩阵行 1:1 覆盖，且无缺失、无重复 owner；
  6. `runtime.yaml`、`execution-plan.yaml`、`resume-pack.yaml`、`latest-summary.md` 已满足机器可判定的一致性规则；
  7. 不修改产品运行时语义，也不关闭非 047 owner 的矩阵行。
- **验证**：
  - `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`
- **完成情况**：
  1. 已新增 `scripts/reconcile_ai_sdlc_state.py`，把 reconciliation inventory、owner ledger、历史镜像 backfill 与 top-level state repair 收敛到同一入口；
  2. 已生成 `reconciliation-inventory.yaml` 与 `matrix-owner-ledger.yaml`；
  3. 已补齐 `006, 010-021, 024-029` 共 19 个 `.ai-sdlc/work-items` 历史镜像；
  4. `.ai-sdlc/state/checkpoint.yml` 已从旧 `WI-023` 收敛到 `WI-047`，`project-state.yaml.next_work_item_seq` 已修正为 `48`。

## Task 47.4 更新执行日志、summary 与 top-level handoff

- **任务编号**：T474
- **状态**：已完成（2026-04-16）
- **目标**：把 047 的 formal truth 收口到可恢复状态，固定下一执行入口。
- **文件**：
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/task-execution-log.md`
  - `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/execution-plan.yaml`
  - `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/runtime.yaml`
  - `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/resume-pack.yaml`
  - `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已明确记录 inventory、owner ledger、state repair 与 residual risk；
  2. `.ai-sdlc` 元数据能准确恢复到 `WI-048` 前的下一执行入口；
  3. latest-summary 已列出最小验证产物与 handoff 纪律；
  4. reviewed docs baseline、approval status 与 canonical branch 已进入 formal truth。
- **验证**：
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已更新 `task-execution-log.md`、`runtime.yaml`、`execution-plan.yaml`、`resume-pack.yaml` 与 `latest-summary.md`；
  2. `WI-047` 已切到 completed state，并把下一执行入口固定为 `WI-048`；
  3. reviewed docs baseline、approval status、canonical branch、inventory 与 owner ledger 证据已进入 formal truth。

## Task 47.5 完成 047 整体验证并交接 WI-048

- **任务编号**：T475
- **状态**：已完成（2026-04-16）
- **目标**：正式关闭 047，并把后续矩阵 owner 按 ledger 交接给 `WI-048` 到 `WI-051`。
- **文件**：
  - `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/task-execution-log.md`
  - `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/latest-summary.md`
  - `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. `tests/test_ai_sdlc_reconciliation.py` 与 `tests/test_long_running_autonomy_doc_contracts.py` 通过；
  2. 047 的最小验证产物已齐全：reconciliation inventory、next seq 证据、缺失镜像补齐清单、owner ledger；
  3. 后续 `WI-048` 到 `WI-051` 已有唯一 owner 依据，不再需要人工二次解释；
  4. formal truth lifecycle 与 owner ledger 完整性都已有机器校验，不再依赖纯人工审阅。
- **验证**：
  - `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`
- **完成情况**：
  1. `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py` 已通过（`10 passed in 0.03s`）；
  2. 仓库内实际校验结果为：`next_seq=48`、`active=047-ai-sdlc-state-reconciliation-and-canonical-gate-repair`、`missing=[]`、`stale=[]`、`lifecycle=[]`；
  3. `WI-048` 可直接消费 `matrix-owner-ledger.yaml` 中 owner=`WI-048` 的条目，不再需要人工二次解释归属。
