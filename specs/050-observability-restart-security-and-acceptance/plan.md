# Plan：050-observability-restart-security-and-acceptance

## 目标

把 `WI-050` 收敛为 release-blocking 的 NFR / availability / observability / acceptance closeout：不再新增入口语义，而是验证并补齐 048/049 已冻结主链路在性能、重启、安全和交付验收上的正式证据。

## 实施原则

1. 继续遵循 `ai_sdlc`：先写失败测试，再做最小实现，再回写 formal memory。
2. 只消费 `WI-048` / `WI-049` 已冻结 contract，不改 canonical semantics。
3. 优先补齐“可验证 evidence”，避免为了观测或验收再引入新的业务真源。
4. 可观测性、健康检查和指标输出必须能被测试或 ops API 直接读取。
5. 重启恢复验证必须覆盖 runtime 侧映射恢复与 watchdog 侧审批/receipt 恢复，不能只做静态 schema 检查。

## 工作流

### Phase 1：冻结 050 formal scope

- 从 PRD 13/14/17、M5 和 owner ledger 中恢复 050 的正式边界；
- 明确 050 只做 observability / restart / security / acceptance closeout；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/050-*`。

### Phase 2：先写 red tests 冻结 NFR / acceptance contract

- 写失败测试锁定：
  - `/healthz` 与 metrics/export surface；
  - 查询路径 P95 或等价性能 evidence contract；
  - A/B 重启恢复后的 project/thread/approval/receipt 可用性；
  - A 不可达时的 fail-closed 错误语义；
  - PRD 17.* 的关键 acceptance 条款。

### Phase 3：实现 observability / health / metrics evidence

- 补齐 `/healthz`、结构化日志、指标导出或 ops evidence；
- 让任务、审批、恢复统计能被正式读取；
- 建立 acceptance evidence bundle 的最小产物。

### Phase 4：实现 restart / security / reliability closeout

- 落实 A/B 重启恢复验证路径；
- 确认 A 不可达时 B 明确 fail-closed；
- 固化安全与可靠性验收用例。

### Phase 5：完成 release-blocking acceptance closeout

- 跑 050 的完整回归；
- 更新 `.ai-sdlc` 记忆；
- 仅把高耦合 hardening 留给 `WI-051`。

## 风险

- 当前仓库存在大量未提交历史改动，050 必须避免误碰非本次 owner 范围；
- 若现有 observability surface 不一致，需优先复用已有接口而不是新造一套；
- 性能目标需以 repo 内可执行 evidence 表达，避免依赖不稳定外部环境。

## 验收

- `WI-050` 完成后，剩余未闭合项只能是 `WI-051` 的高耦合 hardening；
- `.ai-sdlc` 中 active work item、checkpoint、summary、execution-plan 一致；
- release-blocking 的 observability / restart / security / acceptance 条款有正式测试或 evidence。
