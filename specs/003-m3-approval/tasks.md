# 任务分解：003-m3-approval

> 对应规格：`specs/003-m3-approval/spec.md`

## Batch 1：M3 审批实现

### Task 3.1 风险分级与审批存储

- **任务编号**：T31
- **依赖**：无
- **文件**：`src/a_control_agent/risk/classifier.py`, `src/a_control_agent/storage/approvals_store.py`
- **可并行**：否
- **验收标准**：
  1. `classify_risk(command: str) -> str` 返回 L0–L3；
  2. L3 调用路径下 `auto_approve_allowed` 为 False；
  3. 单元测试覆盖典型命令样例。
- **验证**：`pytest tests/test_m3_risk.py -q`

### Task 3.2 A-Control-Agent 审批 API

- **任务编号**：T32
- **依赖**：T31
- **文件**：`src/a_control_agent/api/approvals.py`, `src/a_control_agent/main.py`
- **可并行**：否
- **验收标准**：
  1. `GET /api/v1/approvals`、`POST /api/v1/approvals`、`POST /api/v1/approvals/{id}/decision` 可用且 envelope 统一；
  2. L0/L1 在创建时可按策略自动批准；
  3. 单元测试覆盖鉴权与 L3 不自动通过。
- **验证**：`pytest tests/test_m3_agent_approvals.py -q`

### Task 3.3 Watchdog 审批代理

- **任务编号**：T33
- **依赖**：T32
- **文件**：`src/watchdog/api/approvals_proxy.py`, `src/watchdog/main.py`
- **可并行**：否
- **验收标准**：
  1. `GET/POST` Watchdog 路径与 PRD §10.1.2 语义一致；
  2. A 不可达时返回 CONTROL_LINK_ERROR；
  3. 集成测试 mock httpx。
- **验证**：`pytest tests/test_m3_watchdog_approvals.py -q`
