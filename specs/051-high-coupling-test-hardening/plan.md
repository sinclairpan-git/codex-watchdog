# Plan：051-high-coupling-test-hardening

## 目标

把 `WI-051` 收敛为项目 backlog `BL-2026-04-06-001` 的正式 closeout：不新增产品语义，只把高耦合接缝测试从 review 驱动的点状补丁，升级为显式场景矩阵、替身契约和固定验证入口。

## 实施原则

1. 严格遵循 `ai_sdlc`：先 formalize scope，再写 red tests，再做最小修补，再回写 formal memory。
2. 051 只做测试强化，不承担 release blocker、入口定义或 runtime semantics 改写。
3. 优先消费现有高风险测试，把真正缺口压缩到 fake/stub drift 与 suite topology，而不是继续堆相似 happy path。
4. 矩阵必须面向 seam，而不是面向单文件；同一条链路的桥接、回调、恢复和读侧语义要能被同一份矩阵解释。
5. 若发现真实产品缺口，只记录后续入口，不默认扩大为生产代码改造。

## 工作流

### Phase 1：冻结 051 formal scope

- 从 `WI-050` handoff、owner 约束和 backlog 恢复 051 的正式边界；
- 建立 `spec/plan/tasks/seam-matrix/log` 与 `.ai-sdlc/work-items/051-*`；
- 固定 051 不承接 release blocker。

### Phase 2：先写 red tests 锁定 seam matrix 与 fake/stub contract

- 写失败测试锁定 fake / stub 与真实 `AClient` 的接口签名和关键 keyword-only 约束；
- 写失败测试锁定最小 `seam-smoke` 链路；
- 明确哪些已有 targeted tests 被正式纳入矩阵。

### Phase 3：收敛 targeted / seam-smoke / full 验证入口

- 固定三层验证命令与测试集合；
- 去除重复建设，避免同一 seam 在多个测试文件被无序重复补点；
- 让矩阵、测试名和命令入口可直接互相映射。

### Phase 4：必要时做最小测试基建修补

- 只在 red tests 证明存在真实缺口时，补最小测试基建；
- 优先改测试替身、fixture、命令入口和测试编排；
- 避免把 051 变成生产功能增强项。

### Phase 5：完成 formal closeout

- 跑 targeted / seam-smoke / full 回归；
- 更新 backlog 状态、执行日志与 `.ai-sdlc`；
- 若存在未处理真实产品缺口，只允许形成后续 work item 入口。

## 风险

- 现有高风险测试已经较多，若不先做矩阵和去重，051 很容易沦为重复建设；
- fake / stub 分散在多个测试文件，若只修一处，仍会留下静默漂移点；
- 若过早引入生产代码修补，051 会越过 owner 边界并污染 release-blocking 口径。

## 验收

- `WI-051` 完成后，高耦合接缝有正式矩阵，不再依赖 review 记忆；
- fake / stub contract 能在真实 `AClient` 接口漂移时直接失败；
- `targeted / seam-smoke / full` 三层验证入口有稳定命令和测试集合；
- 051 不承接 release blocker，也不重开 048/049/050 已关闭语义。
