# Spec：056-coverage-audit-snapshot-closeout

## 背景

`WI-055` 完成后，repo-local `python -m ai_sdlc verify constraints` 与外部 `Ai_AutoSDLC` 真值都已经返回通过，当前仓库 formal state 也显示：

- `linked_wi_id=055-checkpoint-string-compatibility`
- `current_stage=completed`
- `next_work_item_seq=56`

但历史输入文档 `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md` 仍保留大量“未落地”结论，且这些结论直接来自 `2026-04-14` 的审计快照，没有与后续 `WI-048` 到 `WI-055` 的 formal closeout 同步。

这会在仓库内部制造两套并行说法：

1. formal truth 与外部真值已经显示 closeout 完成；
2. 历史 coverage audit 快照仍像当前待办列表一样显示“未落地”。

`WI-056` 因此只承担 coverage audit snapshot closeout 的 repo-side 收口：把旧矩阵明确标记为历史快照、提供当前 closeout 汇总入口，并把这条约束纳入 repo-local `verify constraints` 与回归测试。

## 范围

### In Scope

- 为 `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md` 增加 superseded / historical snapshot 标记；
- 新增当前 coverage audit closeout 汇总文档；
- 增加 repo-local validator，防止旧矩阵继续伪装成当前待办真值；
- 增加回归测试；
- 更新 formal docs、`.ai-sdlc` 状态与 closeout 留档。

### Out of Scope

- 不重写 `WI-047` 的 owner ledger；
- 不重新打开 `WI-048` 到 `WI-055` 已关闭的业务或规则面；
- 不把 `docs/superpowers/` 提升为 canonical truth；
- 不修改外部 `Ai_AutoSDLC` 仓库。

## Formal Source

- `docs/architecture/coverage-audit-closeout-execution-design.md`
- `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`
- `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml`
- `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/latest-summary.md`
- `.ai-sdlc/work-items/049-feishu-entrypoint-closure/latest-summary.md`
- `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/latest-summary.md`
- `.ai-sdlc/work-items/051-high-coupling-test-hardening/latest-summary.md`
- `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/latest-summary.md`
- `.ai-sdlc/work-items/053-release-entry-docs-consistency/latest-summary.md`
- `.ai-sdlc/work-items/054-backlog-id-and-verification-profile-mirror/latest-summary.md`
- `.ai-sdlc/work-items/055-checkpoint-string-compatibility/latest-summary.md`

## 非 Owner 约束

- **FR-5601**：056 只关闭 coverage audit snapshot 与 current formal truth 的对账漂移，不修改业务语义。
- **FR-5602**：056 不得把 `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md` 重新当作 canonical truth，只能把它降级为历史快照。
- **FR-5603**：056 不得重写 `matrix-owner-ledger.yaml` 的 owner 分配，也不得手工重开 048-055 的 owner 边界。

## 功能需求

- **FR-5604**：历史矩阵文档必须显式声明自己是 `2026-04-14` 的 snapshot，且已被后续 formal closeout 替代。
- **FR-5605**：仓库中必须存在一个当前 coverage audit closeout 汇总入口，至少说明：
  1. `WI-047` 生成了 row-level owner ledger；
  2. `WI-048`、`WI-049`、`WI-050`、`WI-051` 已完成对应 closeout；
  3. `WI-052` 到 `WI-055` 已完成 repo-side blocker closeout；
  4. 当前应以 `.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/project/config/project-state.yaml` 与各 work item `latest-summary.md` 作为真值。
- **FR-5606**：repo-local `python -m ai_sdlc verify constraints` 必须能发现以下违约：
  1. 旧矩阵缺少 superseded / snapshot 标记；
  2. 当前 closeout 汇总入口缺失；
  3. 旧矩阵未明确指向当前 closeout 汇总入口。
- **FR-5607**：056 必须用回归测试覆盖：
  1. 当前仓库满足 coverage audit snapshot closeout contract；
  2. 缺少 superseded 标记时 validator 失败；
  3. 缺少当前 closeout 汇总入口时 validator 失败。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。056 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/architecture/coverage-audit-closeout-execution-design.md`
   - `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`
   - `docs/architecture/coverage-audit-closeout-status.md`
   - `specs/056-coverage-audit-snapshot-closeout/spec.md`
   - `specs/056-coverage-audit-snapshot-closeout/plan.md`
   - `specs/056-coverage-audit-snapshot-closeout/tasks.md`
   - `specs/056-coverage-audit-snapshot-closeout/task-execution-log.md`
   - `.ai-sdlc/work-items/056-coverage-audit-snapshot-closeout/execution-plan.yaml`
   - `.ai-sdlc/work-items/056-coverage-audit-snapshot-closeout/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
