---
related_doc:
  - "docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md"
  - "specs/029-audit-replay-ops-production-deployment/spec.md"
  - "docs/getting-started.zh-CN.md"
---

# 实施计划：029-audit-replay-ops-production-deployment

## 目标

把完整产品闭环补成可审计、可回放、可部署、可升级、可告警的生产态系统。

## 架构摘要

- **Ops last, not optional**：029 放在最后实现，但一旦进入产品态，它不是可选项。
- **Replay from canonical records**：回放与审计只消费前五个 WI 已产生的 canonical records。
- **No contract rewrite**：029 只补运营面，不反向重写核心业务契约。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Audit / Replay | `src/watchdog/services/audit/service.py`, `src/watchdog/services/audit/replay.py` | 审计查询、forensic replay |
| Ops Surface | `src/watchdog/api/ops.py`, `src/watchdog/api/metrics.py` | operator 查询、健康与指标 |
| Deployment Docs | `README.md`, `docs/getting-started.zh-CN.md`, `docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md` | 安装、升级、回滚、runbook |
| 验证 | `tests/test_watchdog_audit.py`, `tests/test_watchdog_replay.py`, `tests/integration/test_openclaw_integration_spine.py` | 审计、回放、运维关键路径 |

## 边界纪律

- `029` 只拥有审计、回放、部署、升级、告警与 runbook。
- `029` 不反向改动前 5 个 WI 的核心契约。
- 若出现契约缺口，优先登记 defect/backlog，而不是在 029 中偷改语义。

## 分阶段计划

### Phase 1：冻结审计与回放面

- canonical audit query
- replay filters
- forensic semantics

### Phase 2：补 ops surface 与关键告警

- metrics / health
- critical alerts
- operator queries

### Phase 3：补生产化部署与升级

- install / upgrade / rollback
- secret rotation
- 公网方案

### Phase 4：runbook 与验证

- 关键故障 runbook
- replay tests
- install / upgrade validation

## 测试计划

- `tests/test_watchdog_audit.py`
  - canonical records 查询
- `tests/test_watchdog_replay.py`
  - 按 `decision_id / envelope_id / approval_id` 回放
- `tests/integration/test_openclaw_integration_spine.py`
  - A/B restart / restore
  - 接入链路不回归

## 主要风险与应对

- 风险 1：029 借运维名义重写业务契约
  - 应对：冻结“不反向修改前 5 个 WI”
- 风险 2：公网与 secret 管理继续停留在 quick-fix
  - 应对：明确 install / upgrade / rotation 标准流程
- 风险 3：告警只有指标没有处理手册
  - 应对：runbook 与 alerts 必须同时交付

## 验收口径

只有当以下条件同时满足，029 才算完成：

1. canonical records 已可被审计与回放；
2. 关键告警与 runbook 已可支撑长期运行；
3. A/B 部署、升级、回滚与 secret rotation 已有正式方案；
4. 本工作项未反向重写前 5 个 WI 的核心契约。
