# 覆盖性审计矩阵实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出“未落地全量盘点”矩阵，覆盖 PRD + 总实施计划 + 架构文档中所有条款，并按严格证据规则判定未落地项。

**Architecture:** 先抽取条款与锚点，再为每条建立实现/验证/入口证据槽位，缺任一即判未落地；仅输出未落地矩阵并附证据引用。

**Tech Stack:** 纯文档审计（Markdown），使用仓库现有文档/日志/测试作为证据来源。

---

### Task 1: 抽取 PRD 条款并建立证据槽位

**Files:**
- Read: `codex-watchdog-prd.md`
- Create: `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`

- [ ] **Step 1: 逐段抽取 PRD 需求条款**

从 PRD 的“目标/成功标准/关键场景/风险模型”等章节抽取条款，记录来源锚点（章节标题 + 行号）。

- [ ] **Step 2: 为每条 PRD 条款建立矩阵行**

每行包含：来源、条款摘要、实现证据、验证证据、入口证据、缺口类型、结论（未落地）。

- [ ] **Step 3: 初步填充证据槽位**

优先引用 work item summary / 执行日志中的实现或验证线索；无法确认则留空，待后续补充。

- [ ] **Step 4: 保存矩阵草稿**

在 `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md` 中建立“PRD 区块”并填充条目。

---

### Task 2: 抽取实施计划条款并补齐矩阵

**Files:**
- Read: `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
- Modify: `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`

- [ ] **Step 1: 抽取计划内 Task/Step 条款**

重点标记含 MVP/一期/二期或 Release Gate 约束的条款，记录来源锚点。

- [ ] **Step 2: 去重合并 PRD 重复条款**

若条款在 PRD/计划重复出现，合并为单行并在来源列列出全部锚点。

- [ ] **Step 3: 填充证据槽位**

基于 work item summary / 执行日志 / 测试记录补充实现与验证证据；入口证据基于计划引用的 API/路径。

- [ ] **Step 4: 更新矩阵“计划区块”**

按证据最严规则判定未落地，记录缺口类型。

---

### Task 3: 抽取架构与阶段条款并完成矩阵

**Files:**
- Read: `docs/architecture/*`
- Modify: `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`

- [ ] **Step 1: 抽取 MVP/一期/二期与 Release Gate 条款**

重点覆盖“一期通关/Release Gate/MVP/二期”定义，记录来源锚点。

- [ ] **Step 2: 去重合并其他来源条款**

与 PRD/计划重复的条款合并并列出多来源锚点。

- [ ] **Step 3: 填充证据槽位**

优先引用 WI-030~WI-037 等 summary/验证记录，以及 e2e/ops 测试作为验证证据。

- [ ] **Step 4: 完成矩阵与缺口判定**

仅保留“未落地”条目，标注缺口类型与证据格式。

---

### Task 4: 质量复核与交付

**Files:**
- Read: `.ai-sdlc/work-items/*/latest-summary.md`
- Read: `specs/*/task-execution-log.md`
- Modify: `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`

- [ ] **Step 1: 证据完整性校验**

逐行检查证据格式是否满足“文件路径 + 章节/行号 + 证据类型”。

- [ ] **Step 2: 仅保留未落地条目**

删除“已落地”行，确保结果为未落地全量盘点。

- [ ] **Step 3: 对抗评审**

将矩阵交给两位对抗专家复核（Hermes Agent 专家、Anthropic Manager 专家），记录是否有 blocking/P1。

- [ ] **Step 4: 修订并提交**

按评审意见修订矩阵，提交文档变更。

---

### Task 5: 交付说明

**Files:**
- Modify: `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`

- [ ] **Step 1: 添加结论区**

补充简短结论段：未落地条款数量、主要缺口类型分布（实现/验证/入口）。

- [ ] **Step 2: 最终提交**

提交最终矩阵文档。
