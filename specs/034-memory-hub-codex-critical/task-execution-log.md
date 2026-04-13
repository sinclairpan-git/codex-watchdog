# 执行日志：034-memory-hub-codex-critical

## 2026-04-13

- 已完成 `WI-034` formal design v2 重写，原因是初版 `Task 5` 在两条外部约束上都存在关键偏差：
  - 对 Hermes 而言，`Memory Hub` 职责过宽，把 session archive、skills、user model 都包装成 memory 层，且缺少 provider lifecycle 与安全扫描门禁；
  - 对 Anthropic 而言，缺少 session raw event replayability、JIT expansion、brain/hands/sandbox 边界和 packet transform 可替换性。
- 已把 `Task 5` 的官方对齐口径重写为：
  - Hermes 对齐 `persistent memory target + session search + provider lifecycle + skills progressive disclosure + security scanning`
  - Anthropic 对齐 `durable session log + context window 外状态 + JIT expansion + brain/hands/sandbox 解耦`
- 已做出的关键设计决策：
  1. `Memory Hub` 只保留 retrieval/provider facade 与 packet inputs，不拥有 final packet policy；
  2. 四类内容只作为 repo 内部实现分区，不再声称是 Hermes 官方原生分层；
  3. `Session Archive Memory` 调整为 `session search archive` 语义；
  4. 强制增加 `Session Service` 事件切片读取边界；
  5. 强制增加 `security_verdict` 门禁和 `memory_unavailable_degraded` / `memory_conflict_detected` 的 canonical degrade 顺序；
  6. `User Model`、`Periodic Nudge`、`AI_AutoSDLC/Cursor` 等都继续只是 disabled-by-default preview contract。
- 第二轮对抗评审已给出 `approve for spec freeze`，但补充了必须落成正式 contract 的细化项：
  1. provider lifecycle 只能作为 compatibility adapter，provider 操作面限制在 `search|store|manage` 类 memory ops；
  2. `security_verdict` 细化为 `pass|caution|warn|dangerous|quarantine`，其中 `dangerous` 不可 override，shared/external source 的 override 必须留痕；
  3. resident write surface 需要 `add|replace|remove` 或等价语义，并在容量压力下显式 consolidate；
  4. skill body 不能被复制成 resident memory，`Memory Hub` 只存 index/metadata/reference，正文继续由 source-of-truth 提供；
  5. degrade/conflict 事件必须带 `reason_code` 和 `source_ref`；
  6. replayability 验收必须覆盖 compaction 之后的语义级恢复，summary/packet input 不能成为唯一恢复来源；
  7. 需要最小 context quality evaluation 指标，用于后续 release evidence，而不是让 retrieval 质量停留在主观判断。
- 当前尚未开始实现代码；下一步入口固定为 `Task 34.2`，先写 red tests 锁定 contract。
