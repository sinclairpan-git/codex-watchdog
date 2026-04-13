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

执行要求：

1. 先冻结 `certification_packet_corpus` 与 `shadow_decision_ledger`。
2. 再运行 `scripts/generate_release_gate_report.py` 生成唯一有效的 `release_gate_report`。
3. 用生成出的 `report_hash` 和当前输入哈希做 runtime 校验。

约束：

- 禁止人工拼接放行材料。
- 禁止手写 `PASS` 报告替代脚本输出。
- `report_approved_by` 只是报告治理元数据，不能替代当前动作审批。
