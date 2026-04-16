---
related_doc:
  - "docs/architecture/coverage-audit-closeout-execution-design.md"
  - "docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md"
  - "docs/framework-defect-backlog.zh-CN.md"
  - "docs/project-backlog.zh-CN.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/046-session-event-gate-payload-write-contract/spec.md"
---

# AI-SDLC State Reconciliation And Canonical Gate Repair — 功能规格说明

## 概述

`047-ai-sdlc-state-reconciliation-and-canonical-gate-repair` 是在 `WI-046` formal docs 完成后追加的第十八个正式执行 work item。它不再扩新的产品语义、Feishu/OpenClaw 入口、release-gate contract 或测试平台，而是先修复当前仓库已经存在的 AI-SDLC canonical truth 漂移，并为后续 `WI-048` 到 `WI-051` 建立唯一可执行的 owner ledger 与 state gate。

047 要解决的是当前仓库已经明确暴露出来的四类 drift：

> `specs/<wi>` 与 `.ai-sdlc/work-items/<wi>` 不一致  
> `checkpoint.yml` / `project-state.yaml` / active work item 序列不一致  
> `next_work_item_seq` 失真  
> 覆盖性审计矩阵缺少 row-level owner ledger，导致后续条款归属不可机器判定

它只消费已经冻结的边界：

- `docs/architecture/coverage-audit-closeout-execution-design.md`
- `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`
- `docs/framework-defect-backlog.zh-CN.md`
- 现有 `specs/` 与 `.ai-sdlc/work-items/` 目录真值

它同时吸收两组对抗边界：

- **Hermes Agent 专家边界**：047 必须只修复 state truth、mirror inventory、owner ledger 与 gate discipline，不得靠重写矩阵文案或 summary 文字来“关闭”条款。
- **Anthropic Manager 专家边界**：047 必须把 `next_work_item_seq`、缺失镜像清单、owner tie-break 与 formal truth 生命周期写成可机器判定规则；不得一边修状态，一边顺手进入 `WI-048` 之后的产品行为收口。

因此，047 的首要目标不是补需求功能，而是让后续所有 closeout work item 都建立在唯一的 AI-SDLC canonical truth 之上。

## 功能需求

- **FR-4701**：047 必须提供一套单一、确定性的 `next_work_item_seq` 计算规则：读取 `specs/` 与 `.ai-sdlc/work-items/` 的编号并集，取最大值后加 1；不得继续人工凭印象填写下一序号。
- **FR-4702**：047 必须生成当前仓库的 reconciliation inventory，至少列出：已有 `specs/<wi>`、已有 `.ai-sdlc/work-items/<wi>`、缺失镜像 work item、当前 active top-level state、当前 stale pointers。
- **FR-4703**：047 必须补齐当前缺失 `.ai-sdlc/work-items/` 镜像的既有 formal work item，至少覆盖 `006, 010-021, 024-029`。
- **FR-4704**：047 必须把 `.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/project/config/project-state.yaml` 与 active work item runtime 的指针关系收敛到同一序列，不得继续指向不同 WI。
- **FR-4705**：047 必须为覆盖性审计矩阵中全部剩余未落地行生成 row-level owner ledger，至少包含稳定条目标识、唯一 owner WI、non-owner WI、前置依赖 artifact 与当前 gap type；ledger 必须是源矩阵的确定性投影，不得手工漏行、并行重复或摘要化替代。
- **FR-4706**：047 必须固定 owner tie-break 规则：`WI-047 -> WI-048 -> WI-049 -> WI-050 -> WI-051`；混合缺口行不得拆成多 owner。
- **FR-4707**：047 不得直接关闭 `WI-048` 到 `WI-051` owner 的矩阵行；它只能建立 owner ledger 和 gate discipline，不能把 example、summary、兼容壳或文档索引伪装成正式证据。
- **FR-4708**：047 必须把 `execution-plan.yaml` 与 `resume-pack.yaml` 纳入 formal truth lifecycle，禁止出现“名义上是真值、实际上长期过期”的状态；至少要有可机器校验的一致性不变量，能够证明 `runtime.yaml`、`execution-plan.yaml`、`resume-pack.yaml` 与 `latest-summary.md` 没有互相漂移。
- **FR-4709**：047 在进入 `T472` 之前，必须把被评审的 formal docs baseline 固化到机器可判定字段中，至少包括 `docs_baseline_ref`、`docs_baseline_at`、`review_approval_status` 与 `review_approved_by`；未落档前不得进入实现。
- **FR-4710**：047 必须把 active branch pin 到当前 canonical work item，而不是继续沿用旧 WI 的 branch 上下文；branch pinning 必须进入 handoff 与 runtime truth。

## 用户故事

### 用户故事 1：维护者需要可信的 AI-SDLC 当前真值

作为仓库维护者，我需要在任何时刻都能唯一回答“当前 active WI 是什么、下一编号是什么、哪些历史 WI 只有 spec 没有 `.ai-sdlc` 镜像”，否则后续所有 formal docs 和 closeout 都会继续漂移。

场景 1：当前仓库顶层 `checkpoint.yml` 仍指向 `WI-023`，但真实 work item 已推进到 046 之后。047 完成后，系统必须能用确定性算法重算下一序列，并把 stale pointer 显式收敛。

场景 2：某个历史 `specs/<wi>` 存在但 `.ai-sdlc/work-items/<wi>` 缺失。047 完成后，系统必须能列出缺失清单并补齐镜像，而不是继续让历史 WI 只在 specs 中存在。

### 用户故事 2：后续 closeout WI 需要唯一 owner ledger

作为后续 `WI-048` 到 `WI-051` 的执行者，我需要知道每一条矩阵行到底归谁，不允许同一条既被入口批次认领，又被验证批次认领。

场景 1：某条矩阵行同时缺 `无入口 + 无验证`。047 完成后，owner ledger 必须按 tie-break 把它先归到 `WI-049`，而不是由不同执行者分别认领。

场景 2：某条矩阵行同时缺 `无实现 + 无入口`。047 完成后，它必须先归 `WI-048`，入口批次只能在实现完成后接手。

## 非目标

- 不在 047 中补 Feishu / OpenClaw 入口。
- 不在 047 中新增或修改产品运行时语义。
- 不在 047 中关闭 `WI-048` 到 `WI-051` owner 的矩阵行。
- 不在 047 中重写覆盖性审计矩阵的业务条款内容。
- 不在 047 中发明新的 AI-SDLC 目录结构或第二套状态系统。
