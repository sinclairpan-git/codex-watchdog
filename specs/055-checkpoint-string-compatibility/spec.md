# Spec：055-checkpoint-string-compatibility

## 背景

`WI-054` 完成后，repo-local `verify constraints` 与外部 `Ai_AutoSDLC` 真值均已通过，但外部框架在读取当前仓库的 [`checkpoint.yml`](/Users/sinclairpan/project/openclaw-codex-watchdog/.ai-sdlc/state/checkpoint.yml) 时仍会先打印一段 schema 警告，再 fallback 成功。

根因已确认：

- `.ai-sdlc/state/checkpoint.yml` 中的 `pipeline_started_at`、`pipeline_last_updated`、`completed_stages[*].completed_at`、`last_synced_at` 当前是未加引号的 ISO 时间字符串；
- YAML 解析器会把这些值直接提升为 `datetime`；
- 外部 `Ai_AutoSDLC` 的 `Checkpoint` schema 对这些字段要求是 `string`。

`WI-055` 因此只承担 checkpoint YAML 字符串兼容性的 repo-side closeout：修正当前 checkpoint，固定未来写出路径，并增加回归测试与 repo-local gate。

## 范围

### In Scope

- `.ai-sdlc/state/checkpoint.yml` 时间字段加引号；
- `scripts/reconcile_ai_sdlc_state.py` YAML 序列化规则修复；
- checkpoint 字符串兼容性 validator；
- 对当前 checkpoint 和未来 serializer 的回归测试；
- 相关 formal docs、`.ai-sdlc` 状态与 closeout 留档。

### Out of Scope

- 其它 `.ai-sdlc/work-items/*` 文件的大范围格式重写；
- 业务代码、release docs 或 framework backlog 再次扩展；
- 修改外部 `Ai_AutoSDLC` 仓库。

## Formal Source

- `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `### 4.5.4 WI-055：Checkpoint String Compatibility`
- `.ai-sdlc/state/checkpoint.yml`
- `scripts/reconcile_ai_sdlc_state.py`
- 外部框架读取警告：
  - `Ai_AutoSDLC` 读取 `Checkpoint` 时将未加引号 ISO 时间解析为 `datetime`
- `.ai-sdlc/work-items/054-backlog-id-and-verification-profile-mirror/latest-summary.md`
  - `next_work_item_seq=55`

## 非 Owner 约束

- **FR-5501**：055 只关闭 checkpoint YAML 兼容性，不修改业务语义。
- **FR-5502**：055 不修改外部框架仓库，只在当前 repo 建立兼容输出。
- **FR-5503**：055 的新增代码必须可归类为 serializer contract、validator 或 regression tests。

## 功能需求

- **FR-5504**：当前 `.ai-sdlc/state/checkpoint.yml` 在 `yaml.safe_load` 后，以下字段必须保持 `str`：
  - `pipeline_started_at`
  - `pipeline_last_updated`
  - `completed_stages[*].completed_at`
  - `last_synced_at`
- **FR-5505**：未来由 `scripts/reconcile_ai_sdlc_state.py` 写出的 ISO 时间字符串必须自动加引号，避免再次被 YAML 提升为 `datetime`。
- **FR-5506**：repo-local `python -m ai_sdlc verify constraints` 必须覆盖 checkpoint YAML 字符串兼容性。
- **FR-5507**：055 必须用回归测试覆盖以下场景：
  1. 当前 repo checkpoint 通过字符串兼容性校验；
  2. 临时 checkpoint 使用未加引号时间戳时，validator 明确失败；
  3. serializer 对 ISO 时间字符串自动加引号；
  4. 外部 `Ai_AutoSDLC` 读取当前仓库时不再打印 checkpoint schema 警告。

## Docs baseline hash recipe

`docs_baseline_ref` 的生成方式必须唯一且可重现。055 固定使用以下规则：

1. reviewed formal artifact set 固定为以下 repo-root 相对路径，且顺序不得改变：
   - `docs/architecture/coverage-audit-closeout-execution-design.md`
   - `.ai-sdlc/state/checkpoint.yml`
   - `scripts/reconcile_ai_sdlc_state.py`
   - `specs/055-checkpoint-string-compatibility/spec.md`
   - `specs/055-checkpoint-string-compatibility/plan.md`
   - `specs/055-checkpoint-string-compatibility/tasks.md`
   - `specs/055-checkpoint-string-compatibility/task-execution-log.md`
   - `.ai-sdlc/work-items/055-checkpoint-string-compatibility/execution-plan.yaml`
   - `.ai-sdlc/work-items/055-checkpoint-string-compatibility/latest-summary.md`
2. 每个文件读取为文本后，统一做换行归一化：`CRLF`/`CR` 全部转为 `LF`。
3. 若文件末尾没有换行，补一个单一 `LF`；若已存在，则不重复追加额外空行。
4. 构造 canonical digest payload 时，对每个文件按顺序拼接：
   - 一行 `<<<PATH:{repo-root-relative-path}>>>`
   - 该文件归一化后的正文
5. 将整个 payload 作为 UTF-8 字节流计算 `SHA-256`，输出小写十六进制字符串，写入 `docs_baseline_ref`。
