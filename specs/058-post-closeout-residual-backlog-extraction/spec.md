# Spec：058-post-closeout-residual-backlog-extraction

## 背景

`WI-057` 完成后，repo-local `python -m ai_sdlc verify constraints` 已通过，当前 formal truth 已固定到：

- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/project/config/project-state.yaml`
- 各 work item 的 `.ai-sdlc/work-items/<wi>/latest-summary.md`

与此同时，仓库内仍存在三类会继续诱发“还有很多待办未落地”错觉的输入：

1. 原始产品义务来源：`codex-watchdog-prd.md`
2. 目标架构来源：`docs/architecture/codex-long-running-autonomy-design.md`
3. 长程实施计划：`docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`

这三类文档仍然具有 residual candidate source 的价值，但它们已经不能直接充当 live backlog 真值。若继续把历史计划未勾选项、历史审计快照或 source doc 中的未消化义务直接当作当前待办，就会重新打开 `WI-035` 到 `WI-057` 已关闭的 owner 边界。

`WI-058` 因此只承担 post-closeout residual backlog extraction：用 `formal-truth-first` 口径，对 PRD、架构、实施计划中的候选义务做一次 repo-side 正式抽取与裁决，并把当前 residual truth 固定为：

- 一个 repo-level canonical machine-readable ledger；
- 一个 human-readable residual status 入口；
- 一个有限交叉校验的 repo-local validator 与回归测试。

## 范围

### In Scope

- 用 `formal truth > source docs > historical references` 口径抽取 residual candidate；
- 为当前 residual truth 建立唯一 canonical ledger；
- 为当前 residual truth 建立 human-readable status doc；
- 增加 repo-local validator 与回归测试；
- 更新 formal docs、`.ai-sdlc` 状态与设计留档。

### Out of Scope

- 不修改任何产品运行时代码、API 或业务语义；
- 不在 `WI-058` 内直接执行 long-running plan truth sync；
- 不正式切出 `WI-059`；
- 不把 `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md` 或旧 owner ledger 恢复为 live truth；
- 不重开 `WI-035` 到 `WI-057` 已完成的 owner 边界。

## Formal Source

- `codex-watchdog-prd.md`
- `docs/architecture/codex-long-running-autonomy-design.md`
- `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
- `docs/architecture/coverage-audit-closeout-execution-design.md`
- `docs/architecture/coverage-audit-closeout-status.md`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/project/config/project-state.yaml`

## 非 Owner 约束

- **FR-5801**：058 只做 residual extraction truth layer，不修改产品行为。
- **FR-5802**：058 不得把 source docs、历史 matrix、历史 plan checkbox 直接提升为当前 backlog 真值。
- **FR-5803**：058 不得在本轮重写 `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md` 的 checkbox truth，也不得以任何形式正式创建 `WI-059`。
- **FR-5804**：058 必须把 current residual truth 固定为 repo-level 单一 machine-readable source of truth，不允许并列 machine ledger。

## 功能需求

- **FR-5805**：058 必须在 `docs/architecture/long-running-residual-backlog-ledger.yaml` 建立唯一 canonical machine-readable ledger，且 ledger 中每个条目至少要包含：
  1. `residual_id`
  2. `source_refs`
  3. `disposition`，只能是 `satisfied`、`superseded` 或 `residual`
  4. `formal_truth_refs`
  5. `notes`
- **FR-5806**：058 必须在 `docs/architecture/long-running-residual-backlog-status.md` 建立 human-readable status 入口，至少说明：
  1. 当前采用 `formal-truth-first` 口径；
  2. canonical ledger 的路径；
  3. 当前 residual 总结；
  4. 若无真实残项，则显式写出 `NO_RESIDUAL_BLOCKERS`。
- **FR-5807**：repo-local validator 必须覆盖以下 contract：
  1. canonical ledger 存在；
  2. residual status doc 存在；
  3. status doc 指向 canonical ledger；
  4. ledger 中每个条目都具备 `source_refs` 与 `formal_truth_refs`；
  5. status doc 结论与 ledger 一致；
  6. ledger 为空时，status doc 必须显式声明 `NO_RESIDUAL_BLOCKERS`。
- **FR-5808**：validator 的强度必须限定为有限交叉校验；它只验证声明出来的 residual truth 是否自洽，不从 PRD、架构、实施计划全文自动反推全覆盖义务。
- **FR-5809**：058 必须用回归测试覆盖：
  1. 当前仓库满足 residual backlog contract；
  2. ledger 条目缺少 `source_refs` 或 `formal_truth_refs` 时 validator 明确失败；
  3. status doc 与 ledger 结论不一致时 validator 明确失败；
  4. 空 ledger + `NO_RESIDUAL_BLOCKERS` 为合法状态。
- **FR-5810**：058 的 formal 输出可以记录 `WI-059` 为候选 next WI，但只有在 residual extraction 结果显示仍需 long-running plan truth sync 时才允许提名；若 ledger 为空，不得强行制造后续 WI。

## 目标文件边界

### 本批应新增或修改

- `docs/architecture/long-running-residual-backlog-ledger.yaml`
- `docs/architecture/long-running-residual-backlog-status.md`
- `src/watchdog/validation/long_running_residual_contracts.py`
- `tests/test_long_running_residual_contracts.py`
- `src/watchdog/validation/__init__.py`
- `ai_sdlc/cli.py`

### 本批明确不应触碰

- `src/watchdog/services/**`
- `src/watchdog/api/**`
- `src/a_control_agent/**`
- `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
- `codex-watchdog-prd.md`
- `docs/architecture/codex-long-running-autonomy-design.md`

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。058 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `codex-watchdog-prd.md`
   - `docs/architecture/codex-long-running-autonomy-design.md`
   - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
   - `docs/architecture/coverage-audit-closeout-status.md`
   - `specs/058-post-closeout-residual-backlog-extraction/spec.md`
   - `specs/058-post-closeout-residual-backlog-extraction/plan.md`
   - `specs/058-post-closeout-residual-backlog-extraction/tasks.md`
   - `specs/058-post-closeout-residual-backlog-extraction/task-execution-log.md`
   - `.ai-sdlc/work-items/058-post-closeout-residual-backlog-extraction/execution-plan.yaml`
   - `.ai-sdlc/work-items/058-post-closeout-residual-backlog-extraction/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
