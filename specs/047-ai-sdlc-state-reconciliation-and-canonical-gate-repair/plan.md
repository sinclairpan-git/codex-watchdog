---
related_doc:
  - "docs/architecture/coverage-audit-closeout-execution-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/spec.md"
---

# 实施计划：047-ai-sdlc-state-reconciliation-and-canonical-gate-repair

## 目标

把 AI-SDLC 当前 canonical truth 修到可机器判定的状态：补齐缺失 `.ai-sdlc/work-items` 镜像、收敛顶层 state pointer、固定 `next_work_item_seq` 算法，并生成覆盖性审计矩阵的 row-level owner ledger。

## 架构摘要

- **Inventory first**：先统一扫描 `specs/` 与 `.ai-sdlc/work-items/`，生成 deterministic inventory，而不是手工核对目录。
- **One reconciliation seam**：通过统一的 reconciliation helper 计算 `next_work_item_seq`、缺失镜像集合、stale pointer 与 owner ledger。
- **Docs + artifact closeout only**：047 只修 formal truth 与 gate discipline，不改产品行为、不关业务条款。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/*` | 冻结 047 边界、任务拆解、执行日志与 handoff |
| Reconciliation validator | `src/watchdog/validation/ai_sdlc_reconciliation.py` | 统一计算 known WI、缺失镜像、`next_work_item_seq`、owner ledger 与 stale pointer |
| Formal artifact generator | `scripts/reconcile_ai_sdlc_state.py` | 生成 reconciliation inventory / owner ledger，供仓库内验证与手工审阅复用 |
| Contract tests | `tests/test_ai_sdlc_reconciliation.py` | 锁定 deterministic seq、缺失镜像检测、owner tie-break 与 stale pointer 校验 |
| Top-level AI-SDLC state | `.ai-sdlc/state/checkpoint.yml`, `.ai-sdlc/project/config/project-state.yaml` | 收敛 active WI 指针与下一 work item 序列 |
| Historical mirror backfill | `.ai-sdlc/work-items/{006,010-021,024-029}/*` | 为缺失镜像的既有 formal WI 提供最小 canonical metadata |
| Review gate metadata | `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/runtime.yaml`, `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/resume-pack.yaml` | 固定 reviewed docs baseline、approval status、approved_by 与 canonical branch |
| Lifecycle invariants | `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/runtime.yaml`, `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/execution-plan.yaml`, `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/resume-pack.yaml`, `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/latest-summary.md` | 固定 formal truth 的字段级一致性，不允许文件存在但内容过期 |
| Reconciliation artifacts | `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/reconciliation-inventory.yaml`, `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml` | 固化 047 产出的 inventory 与 row-level owner ledger |

## 边界纪律

- 047 不得修改任何产品运行时语义、入口或自动化策略。
- 047 不得通过修改 summary / README / matrix 文案来伪造条款关闭。
- 047 不得把 `examples/`、`fixtures`、`latest-summary.md`、`task-execution-log.md` 当作矩阵关闭证据。
- 047 只建立 state truth 与 owner gate；后续条款关闭仍由 `WI-048` 到 `WI-051` 完成。
- 047 的实现 gate 必须附带 reviewed docs baseline 与 approval status；没有 review approval artifact，不得从 `T471` 进入 `T472`。
- 047 必须把 owner ledger 的覆盖率、唯一性与无重复归属做成机器校验，不能只靠人工审阅。
- 047 必须把 `runtime.yaml`、`execution-plan.yaml`、`resume-pack.yaml`、`latest-summary.md` 的一致性做成机器校验，不能只要求“同步更新”。

## 测试计划

- `tests/test_ai_sdlc_reconciliation.py`
- `tests/test_long_running_autonomy_doc_contracts.py`

## Review Gate

`T471` 完成的最小机器门禁为：

- `runtime.yaml` 与 `resume-pack.yaml` 中存在一致的 `docs_baseline_ref`
- `docs_baseline_at` 已记录评审完成时间
- `review_approval_status == approved`
- `review_approved_by` 至少包含 `Anthropic Manager Expert` 与 `Hermes Agent Expert`
- `current_branch` 已 pin 到当前 canonical WI
- `T472` 的红测会直接断言 `runtime.yaml` 与 `resume-pack.yaml` 中这组 review gate 字段完全一致

缺任一项，都不得开始 `T472`

## 交付物

- `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/reconciliation-inventory.yaml`
- `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml`
- `.ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/*`
- 已补齐的 `.ai-sdlc/work-items/{006,010-021,024-029}/*`
