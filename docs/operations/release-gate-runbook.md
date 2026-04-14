# Release Gate Runbook

`release_gate_report` 只能通过 `scripts/generate_release_gate_report.py` 生成。

必备产物：

- `tests/fixtures/release_gate_packets.jsonl`
- `tests/fixtures/release_gate_shadow_runs.jsonl`
- `tests/fixtures/release_gate_label_manifest.json`
- `release_gate_report`

报告必须包含并归档以下字段：

- `label_manifest`
- `generated_by`
- `report_approved_by`
- `artifact_ref`
- `runtime_contract_surface_ref`
- `runtime_gate_reason_taxonomy`

执行要求：

1. 先冻结 `certification_packet_corpus` 与 `shadow_decision_ledger`。
2. 再运行 `scripts/generate_release_gate_report.py` 生成唯一有效的 `release_gate_report`。
3. 用生成出的 `report_hash` 和当前输入哈希做 runtime 校验。

## Refresh / Rebuild Contract

- `scripts/refresh_release_gate_artifacts.py` 是 `release_gate_report` refresh、archive rebuild 与 fixture regeneration 的唯一正式命令。
- 这条命令只能复用现有 `scripts/generate_release_gate_report.py`、`src/watchdog/services/brain/release_gate_report_material.py` 与 shared loader；禁止局部重写 hash/material 或手写 report 构造逻辑。
- refresh 成功的最低标准是：输出 report 立即通过 shared loader 校验；如果 loader 不接受，就视为 refresh 失败。
- operator 如需执行 archive rebuild 或 fixture regeneration，也必须通过这条命令完成，不能分散成手工步骤。
- 禁止人工编辑 JSON、手工猜 `report_hash`、手工拼装 `report_id` 或绕过 loader 校验。
- 041 只正式化这条单一 refresh 命令，不引入新的 manifest、archive metadata model 或额外平台层。

## Runtime Contract Surface

- runtime contract 的唯一配置入口是 `Settings.build_runtime_contract(...)`。
- `release_gate_report` 必须把这条入口归档到 `runtime_contract_surface_ref`，禁止 report 与 runtime 口径分叉。
- `provider / replay / resident runtime` 必须消费同一份 contract 字段集合，至少包括 `provider`、`model`、`prompt_schema_ref`、`output_schema_ref`、`tool_schema_hash`、`risk_policy_version`、`decision_input_builder_version`、`policy_engine_version`、`memory_provider_adapter_hash`。
- `provider_certification`、decision replay、resident orchestrator 只能复用这条统一入口，禁止调用方手写 runtime contract 或私自裁剪字段。

## Runtime Gate Reason Taxonomy

- ops 侧告警标签必须基于稳定 taxonomy 聚合，禁止直接把 raw degrade_reason 暴露成最终 alert code 或 metrics label。
- `release_gate_report` 必须把这组规则归档到 `runtime_gate_reason_taxonomy`，确保 fixture、脚本产物与 runtime/read-side 使用同一套 bucket 定义。
- 以下原因保持原样透传：`approval_stale`、`report_expired`、`report_load_failed`、`input_hash_mismatch`。
- 以下 validator 侧原因统一折叠到 `validator_degraded`：`memory_conflict`、`memory_unavailable`、`goal_contract_not_ready`、`validator_missing`、`validator_blocked`。
- 其他所有 `*_mismatch` 原因统一折叠到 `contract_mismatch`。
- 空值或未分类原因统一归到 `unknown`。

## Runtime Load Validation

- resident runtime 只能通过 `parse_release_gate_report(...)` 加载 `release_gate_report`，禁止直接绕过 helper 手写 `model_validate(...)`。
- report 文件必须是 JSON object；`[]`、`null`、字符串或其他非对象 payload 都视为非法输入。
- `runtime_contract_surface_ref` 与 `runtime_gate_reason_taxonomy` 必须和 canonical JSON contract 完全一致，不能依赖默认值补全、类型宽松或 Python 相等语义蒙混过关。
- load-time 校验失败一律按 `report_load_failed` fail-closed，禁止继续走 auto execute。

约束：

- 禁止人工拼接放行材料。
- 禁止手写 `PASS` 报告替代脚本输出。
- `report_approved_by` 只是报告治理元数据，不能替代当前动作审批。
