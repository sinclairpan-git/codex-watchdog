# 执行日志：040-release-gate-report-material-contract-and-hash-unification

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-039` 的 handoff，正式追加 `WI-040`。
- 把目标边界收紧为：
  - `release_gate_report` 的 canonical material、`report_id` seed 与 `report_hash` 计算必须通过单一 shared helper；
  - generator script、loader、fixture refresh 与测试不得再各自维护局部 hash/material helper；
  - 040 不扩新的 release gate policy、evidence bundle 或 read-side surface；
  - 后续任何 report refresh / validation 都必须复用同一 shared report material contract。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/040-*` 基线。
- 对抗复核：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。
- 当前下一执行入口固定为 `T402`：先写失败测试锁定 shared report material/hash contract，再进入实现。

### Phase 2：red tests 锁定 shared report material/hash contract

- 在 `tests/test_watchdog_release_gate.py` 新增红测，锁定：
  - `watchdog.services.brain.release_gate_report_material` 模块与 `canonicalize_release_gate_report_material / build_release_gate_report_id / stable_release_gate_report_hash` surface 必须存在；
  - checked-in fixture 里的 `report_id/report_hash` 必须能由 shared helper 重建；
  - loader 的 `raw_payload_hash` 必须与 shared helper 结果一致。
- 初次 red 结果：
  - `uv run pytest -q tests/test_watchdog_release_gate.py -k 'report_material_module_exports_shared_contract or report_material_helpers_rebuild_fixture_and_loader_hash'` -> `2 failed`
- 红测确认的真实缺口：
  - `release_gate_report_material` 模块尚不存在；
  - script 与 loader 仍分别维护局部 hash/material helper。

### Phase 3：实现 shared report material/hash helper 并收敛 generator / loader

- 新增 `src/watchdog/services/brain/release_gate_report_material.py`：
  - `canonicalize_release_gate_report_material(payload)` 统一 report material；
  - `build_release_gate_report_id(payload)` 固定 `artifact_ref/sample_window/shadow_window/input_hash/generated_by/report_approved_by` seed；
  - `stable_release_gate_report_hash(payload)` 对 canonical material 计算 `report_hash`。
- 修改 `scripts/generate_release_gate_report.py`：
  - 删除本地 `_stable_report_hash(...)` 与内联 `report_seed`；
  - 改为只导入 shared helper 计算 `report_id/report_hash`。
- 修改 `src/watchdog/services/brain/release_gate_loading.py`：
  - 删除本地 `_stable_report_hash(...)`；
  - 改为只导入 shared helper 计算 loader 侧 `raw_payload_hash`。
- 实现过程中暴露并收掉一处真实契约缺口：
  - 当前 script 生成的 canonical report fixture 含 `shadow_decision_count` / `certification_packet_count`；
  - loader 侧 `ReleaseGateReport` schema 之前会把它们当 extra field 拒绝；
  - 现已把这两个字段补进 `src/watchdog/services/brain/release_gate.py`，使 script 产物与 loader schema 对齐。
- 代码提交：`60775e0 feat: unify release gate report material contract`。
- 对抗复核：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。

### Phase 4：完成 handoff 与 formal close-out

- 已同步 `tasks.md`、执行日志、总实施计划 Task 11 复选框与 `.ai-sdlc/work-items/040-*` 元数据。
- `WI-040` 现在是 release gate report material/hash shared contract 的正式完成态。
- 后续任何 report refresh、archive rebuild、fixture regeneration 或 validation 入口，都只能复用 `src/watchdog/services/brain/release_gate_report_material.py`，不得再复制 `_stable_report_hash(...)` 或局部 `report_seed`。
