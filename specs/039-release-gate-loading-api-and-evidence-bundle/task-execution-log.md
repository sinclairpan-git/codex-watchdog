# 执行日志：039-release-gate-loading-api-and-evidence-bundle

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-035` 的 handoff 与 `WI-037`/`WI-038` 的落地状态，正式追加 `WI-039`。
- 把目标边界收紧为：
  - `release_gate_report` 的加载、校验、hash exactness、runtime contract drift 判定必须通过单一 shared loading API；
  - formal artifacts 与 blocker metadata 必须通过单一 `release_gate_evidence_bundle` surface 回读；
  - runtime、ops/read-side 与后续任何入口都不得继续复制 parse/validate 逻辑；
  - 039 不扩新的 gate policy、risk taxonomy 或放行门槛。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/039-*` 基线。
- 对抗复核：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。
- 当前下一执行入口固定为 `T392`：先写失败测试锁定 shared loading / evidence bundle contract，再进入实现。

### Phase 2：red tests 锁定 shared loading / evidence bundle contract

- 新增 `tests/test_watchdog_release_gate.py` 红测，锁定：
  - `watchdog.services.brain.release_gate_loading` 模块与 `LoadedReleaseGateArtifacts / load_release_gate_artifacts` surface 必须存在；
  - tampered report 即使 schema 看起来合法，只要 canonical `report_hash` 漂移，就必须 fail closed。
- 新增 `tests/test_watchdog_release_gate_evidence.py` 红测，锁定 `ReleaseGateEvidenceBundle` 必须正式承载 `label_manifest_ref / generated_by / report_approved_by / report_id / report_hash / input_hash`。
- 扩展 `tests/test_watchdog_ops.py` 与 `tests/test_watchdog_session_spine_runtime.py`，锁定：
  - ops blocker 必须直接暴露 canonical metadata；
  - runtime success / degraded path 都必须挂统一 `release_gate_evidence_bundle`；
  - 非对象 JSON、治理漂移与 report 损坏都必须 `report_load_failed`，且保留 canonical artifact refs。
- 首轮红测确认暴露的缺口：
  - `release_gate_loading` 模块尚不存在；
  - `ReleaseGateEvidenceBundle` 额外字段被拒绝；
  - ops/read-side 未暴露 metadata；
  - runtime evidence bundle success/failure surface 不一致。

### Phase 3：实现 shared loader / evidence bundle 并收敛 consumer

- 新增 `src/watchdog/services/brain/release_gate_loading.py`：
  - 统一读取 JSON report；
  - 先通过 `parse_release_gate_report(payload)` 做 schema 校验；
  - 对去掉 `report_hash` 的 canonical JSON 计算 sha256，锁定 hash exactness；
  - 输出 `LoadedReleaseGateArtifacts(report, raw_payload_hash, runtime_contract, evidence_bundle)`。
- 扩展 `src/watchdog/services/brain/release_gate_evidence.py`，把 formal artifacts 与治理元数据收敛进单一 `ReleaseGateEvidenceBundle`。
- 修改 `src/watchdog/services/session_spine/orchestrator.py`：
  - 成功路径只消费 shared loader 输出；
  - `report_load_failed` 路径也输出最小 canonical evidence bundle，维持 downstream consume contract。
- 修改 `src/watchdog/api/ops.py`，让 blocker read-side 直接回读 `label_manifest_ref / generated_by / report_approved_by`。
- 在对抗复核指出 exactness 与失败路径 surface 仍需收口后，补了：
  - canonical hash drift red test；
  - failure evidence bundle 的稳定最小面；
  - 与 generator 一致的 `report_hash` 计算材料。
- 代码提交：`8547d40 feat: share release gate loading contract`。
- 对抗复核：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。

### Phase 4：完成 handoff 与 formal close-out

- 已同步 `tasks.md`、执行日志、总实施计划 Task 10 复选框与 `.ai-sdlc/work-items/039-*` 元数据。
- `WI-039` 现在是 release gate shared loading / bundle contract 的正式完成态。
- 后续任何 release gate consumer 如需扩展，只能复用 `src/watchdog/services/brain/release_gate_loading.py` 与 canonical `ReleaseGateEvidenceBundle`，不得再复制 parse/validate 或构造 read-side 第二真相。
