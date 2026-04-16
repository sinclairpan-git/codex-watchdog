# 覆盖性审计清零执行设计（AI-SDLC Canonical）

## 1. 目标

本设计用于把仓库当前覆盖性审计中的未落地条款，按照 AI-SDLC 的 canonical 约束拆分为可执行 work item，并要求每个条款只有在同时具备：

1. 实现证据
2. 验证证据
3. 正式入口证据

之后，才允许从未落地矩阵中移除。

当前总账来源为：

- `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`
- `docs/project-backlog.zh-CN.md`
- `docs/framework-defect-backlog.zh-CN.md`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/project/config/project-state.yaml`

## 2. Canonical 约束

### 2.1 正式真值目录

本轮执行只承认以下目录和文件作为 formal truth。

其中分为两类：

1. **主关闭产物**：直接参与 work item 关闭判定
2. **同步镜像产物**：不是单独的关闭替代物，但既然被列入 canonical truth，就必须在对应阶段同步维护

#### 主关闭产物

- `specs/<work-item>/spec.md`
- `specs/<work-item>/plan.md`
- `specs/<work-item>/tasks.md`
- `specs/<work-item>/task-execution-log.md`
- `.ai-sdlc/work-items/<work-item>/runtime.yaml`
- `.ai-sdlc/work-items/<work-item>/latest-summary.md`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/project/config/project-state.yaml`

#### 同步镜像产物

- `.ai-sdlc/work-items/<work-item>/execution-plan.yaml`
- `.ai-sdlc/work-items/<work-item>/resume-pack.yaml`

`docs/superpowers/` 下的设计、计划、矩阵只作为审计输入、辅助设计或过程产物，不得作为本项目的正式执行真值。

如果某个文件被列入以上两类 formal truth，它就必须有明确的生命周期和同步责任；不得出现“名义上是真值，实际上长期过期”的状态。

### 2.2 状态推进纪律

任何一个新 work item 都必须按以下顺序推进：

1. `spec`
2. `plan`
3. `tasks`
4. `.ai-sdlc/work-items/<wi>/execution-plan.yaml` 与 `runtime.yaml` 初始化
5. implementation
6. verification
7. `task-execution-log.md`、`latest-summary.md` 与 `resume-pack.yaml` 同步
8. matrix 对账
9. 顶层 `.ai-sdlc` 状态同步

不得先 coding 再回填 formal docs。

任何一个 WI 若被判定为已完成，则以下文件不得仍停留在旧阶段或旧 work item：

- `spec.md`
- `plan.md`
- `tasks.md`
- `task-execution-log.md`
- `runtime.yaml`
- `latest-summary.md`
- `execution-plan.yaml`
- `resume-pack.yaml`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/project/config/project-state.yaml`

### 2.3 条款关闭纪律

矩阵中的条款只有在以下三类证据同时存在时才允许关闭：

- 实现：代码、配置、可运行模块
- 验证：测试、验收脚本、可执行检查
- 入口：主链路 API、CLI、运行时路由

三类证据的允许来源固定如下：

- **实现证据允许**：`src/` 下代码、正式配置、运行时脚本、真实服务模块
- **验证证据允许**：`tests/` 下可执行测试、专门的验收脚本、基准脚本、命令输出留档
- **入口证据允许**：live API route、正式 CLI 命令、正式 runtime route、被主链路实际消费的控制面入口

三类证据的禁止来源固定如下：

- `examples/` 中的示例脚本
- `fixtures`
- `latest-summary.md`
- `task-execution-log.md`
- 设计文档、计划文档、README 文案
- 兼容壳如果没有被主链路实际消费

上述文档与 summary 最多只能作为索引，不能作为关闭矩阵条款的主证据。

## 3. 当前问题归类

### 3.1 P0：框架状态与 formal 记忆漂移

当前存在以下 canonical 漂移：

- `.ai-sdlc/state/checkpoint.yml` 仍停留在旧的 `WI-023 / verify`
- `.ai-sdlc/project/config/project-state.yaml` 仍保留旧的 `next_work_item_seq`
- 若干 `specs/<wi>/` 已存在，但缺少对应 `.ai-sdlc/work-items/<wi>/` 镜像
- framework defect backlog 已存在，但尚未被纳入后续批次的执行门禁

截至当前仓库状态，已确认缺少 `.ai-sdlc/work-items/` 镜像的 `specs/` work item 为：

- `006-m5-hardening`
- `010-openclaw-integration-spine`
- `011-stable-session-events`
- `012-stable-recovery-execution`
- `013-stable-action-receipts`
- `014-stable-supervision-evaluation`
- `015-stable-session-explanations`
- `016-stable-approval-inbox`
- `017-stable-session-directory`
- `018-stable-native-thread-resolution`
- `019-stable-workspace-activity`
- `020-stable-operator-guidance`
- `021-stable-session-event-snapshot`
- `024-resident-supervision-session-spine-persistence`
- `025-policy-engine-decision-evidence`
- `026-canonical-action-approval-response-loop`
- `027-outbox-delivery-retry-receipt`
- `028-openclaw-webhook-response-api-reference-runtime`
- `029-audit-replay-ops-production-deployment`

`WI-047` 必须把这份 inventory 固化为机器可校验的 reconciliation ledger。

### 3.1.1 序列归一化算法

本轮执行固定采用以下算法计算 `next_work_item_seq`：

1. 读取 `specs/` 下所有 `NNN-` 前缀
2. 读取 `.ai-sdlc/work-items/` 下所有 `NNN-` 前缀
3. 取两者并集中的最大数值 `max_wi`
4. 令 `next_work_item_seq = max_wi + 1`

该算法允许编号稀疏，不要求历史 work item 连续；但禁止人工凭印象填写下一个编号。

### 3.2 P1：纯无实现缺口

矩阵中存在一组 `无实现、无验证、无入口` 的条款，主要集中于：

- 等待指引模板
- 打断循环模板
- 目标不清晰时请求人工决策
- 严重阈值时人工接管
- 缺失稳定动作映射
- Memory Hub 一期未交付条款
- 生产化闭环缺口

### 3.3 P2：正式入口缺口

大部分未落地条款已有一定实现或验证，但仍缺少正式入口。典型表现为：

- 只有 stable API，没有主控制面自然语言入口
- 只有 OpenClaw 示例脚本，没有正式运行时路由
- 只有 read-side / internal contract，没有可被主链路消费的触达面

### 3.4 P3：验证与非功能缺口

主要包括：

- 性能基准
- 重启恢复验证
- 安全与权限边界验收
- 可靠性与 observability 验收
- 最终交付物中的测试报告样例和形式化验证留档

### 3.5 P4：专项测试强化

项目 backlog 中已确认存在一条 deferred 项：

- `BL-2026-04-06-001` 前端强化后执行测试模块强化

该项属于专门的高耦合接缝测试补强，不与上游功能闭环混做。

## 4. Work Item 拆分

本轮执行固定拆分为 5 个 canonical work item。

### 4.1 WI-047：AI-SDLC State Reconciliation And Canonical Gate Repair

负责：

- 修复 `.ai-sdlc` 顶层状态漂移
- 为缺失镜像的既有 `specs/` work item 补齐 `.ai-sdlc/work-items/`
- 明确 framework backlog 对后续 work item 的门禁作用
- 为后续矩阵关闭建立唯一状态真值
- 产出矩阵 owner ledger，给后续每个剩余条款分配唯一主 WI

关闭条件：

- `project-state.yaml.next_work_item_seq` 已按“最大已知 WI + 1”算法重算
- `checkpoint.yml`、`project-state.yaml`、当前 active WI 的 `runtime.yaml` 不再互相指向不同序列
- 上述缺失镜像清单已补齐对应 `.ai-sdlc/work-items/<wi>/`
- `execution-plan.yaml` / `resume-pack.yaml` 已纳入同步责任，不再游离于关闭门槛之外
- framework defect backlog 已映射到后续执行纪律
- 已生成剩余矩阵条款的唯一 owner ledger；若 ledger 缺失，`WI-048` 到 `WI-051` 不得开始

### 4.2 WI-048：Missing Runtime Semantics And Action Surface

负责：

- 补齐纯无实现的运行时语义
- 补齐缺失稳定动作及其 canonical 路由映射
- 补齐人工决策、人工接管、等待指引、打断循环等核心行为

关闭条件：

- 本批负责的纯无实现条款全部具备实现、验证、入口三证
- 不引入与当前批次无关的新抽象层

### 4.3 WI-049：Feishu And OpenClaw Entrypoint Closure

负责：

- 把现有 Feishu control-plane 与 OpenClaw 模板升级为正式主链路入口
- 收敛自然语言语义到 canonical route
- 关闭以 `无入口` 为主的大批矩阵条款

关闭条件：

- 主链路可从正式入口触达 progress / approval / recovery / control
- OpenClaw / Feishu 入口与 stable route 的映射具备形式化验证
- 入口证据必须是 live route 或被主链路实际消费的 runtime surface，不能使用 `examples/`、summary 或兼容壳冒充

### 4.4 WI-050：Verification And NFR Closeout

负责：

- 补齐性能、重启、安全、可靠性、交付物等验证面
- 形成测试报告样例、验收留档和正式回归清单

关闭条件：

- 本批负责条款的验证缺口全部关闭
- 回归结果已记录到 `latest-summary` 与 `task-execution-log`
- 相关测试、基准、重启验证和验收脚本的命令输出已形成正式留档

### 4.5 WI-051：High-Coupling Test Hardening

负责：

- 执行项目 backlog 中 deferred 的专项测试强化
- 对 approval / callback / restart / session spine 等高耦合接缝建立矩阵式验证

关闭条件：

- 已形成专项 formal spec / plan / tasks
- 回归矩阵与测试替身契约已固定
- backlog 条目已被消化或重标状态

### 4.5.1 WI-052：Framework Defect Gate And Path Discipline

负责：

- 消化 `docs/framework-defect-backlog.zh-CN.md` 中剩余的 `FD-2026-04-05-001`、`FD-2026-04-05-002`、`FD-2026-04-07-003`
- 把 framework backlog、canonical path classifier 与 repo-local `ai_sdlc` 约束入口收敛为仓库内可执行真值

关闭条件：

- 已形成专项 formal spec / plan / tasks
- 仓库内可直接执行 `python -m ai_sdlc verify constraints`
- framework backlog 缺省、formal 文档路径漂移与 `docs/superpowers` 误落点均有回归测试

### 4.5.2 WI-053：Release Entry Docs Consistency

负责：

- 消化 release entry docs consistency 这组固定交付物 blocker
- 把 `README.md`、`docs/releases/v0.6.0.md`、`USER_GUIDE.zh-CN.md`、`packaging/offline/README.md`、`docs/框架自迭代开发与发布约定.md`、`docs/pull-request-checklist.zh.md` 收敛成 repo-local 可校验真值

关闭条件：

- 已形成专项 formal spec / plan / tasks
- repo-local `verify constraints` 覆盖 release docs consistency
- `v0.6.0` release entry docs 与 checklist / policy 无漂移

### 4.5.3 WI-054：Backlog ID And Verification Profile Mirror

负责：

- 修复 framework defect backlog 条目标题格式，使 `FD-*` 引用可被外部框架稳定识别
- 补齐 `src/ai_sdlc/rules/verification.md`，并把 verification profile surface 镜像纳入 repo-local gate

关闭条件：

- 已形成专项 formal spec / plan / tasks
- repo-local `verify constraints` 覆盖 backlog reference 与 verification profile mirror
- 外部框架对 backlog reference 与 verification profile 的剩余 blocker 清零

### 4.5.4 WI-055：Checkpoint String Compatibility

负责：

- 修复 `.ai-sdlc/state/checkpoint.yml` 中时间字段被 YAML 解析为 `datetime` 的兼容性风险
- 固定未来生成路径，使 checkpoint 时间字段保持字符串语义

关闭条件：

- 已形成专项 formal spec / plan / tasks
- 当前 checkpoint 在 YAML 解析后相关时间字段为 `str`
- 外部框架读取 checkpoint 时不再出现 `datetime -> string` schema 警告

### 4.5.5 WI-056：Coverage Audit Snapshot Closeout

负责：

- 把 `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md` 明确降级为历史快照
- 提供当前 coverage audit closeout 汇总入口
- 把 snapshot superseded contract 纳入 repo-local `verify constraints`

关闭条件：

- 已形成专项 formal spec / plan / tasks
- 历史矩阵显式标记为 superseded snapshot
- 当前 closeout 汇总入口存在且指向 `.ai-sdlc` 与各 WI `latest-summary`
- repo-local `verify constraints` 覆盖 snapshot contract

### 4.5.6 WI-057：Task Doc Status Sync

负责：

- 修复 completed work item 的 `specs/<wi>/tasks.md` 状态漂移
- 把 task-doc status sync contract 纳入 repo-local `verify constraints`

关闭条件：

- 已形成专项 formal spec / plan / tasks
- completed WI 的 `tasks.md` 不再残留 `进行中`、`待开始`、`未开始`
- repo-local `verify constraints` 覆盖 task-doc status sync

## 4.6 Owner Ledger 与依赖图

### 4.6.1 高层 owner 分配

后续矩阵条款按以下规则分配：

| Owner WI | 负责条款类型 | 非 owner 约束 |
| --- | --- | --- |
| `WI-047` | 状态真值修复、镜像补齐、owner ledger 建立、framework gate 修复 | 不关闭产品功能条款 |
| `WI-048` | 当前缺口类型含 `无实现` 或 `实现缺口` 的运行时语义 / 动作面条款 | 不负责自然语言入口与渠道运行时闭环 |
| `WI-049` | Feishu / OpenClaw / natural-language 到 canonical route 的正式入口条款 | 不新增 `WI-048` 未定义的新产品语义 |
| `WI-050` | 以验证、性能、重启、安全、可靠性、最终交付物为主的剩余矩阵条款 | 不新增新的产品语义；只补验证和验收闭环 |
| `WI-051` | `BL-2026-04-06-001` 项目 backlog | 默认不拥有任何矩阵行；除非 `WI-050` 在 latest-summary 中显式 handoff |
| `WI-052` | framework defect backlog 与 canonical path / constraint gate | 不关闭业务功能条款；只收敛 repo-local framework contract |
| `WI-053` | release entry docs consistency 与 repo-local release gate | 不实现打包或发布自动化；只固定 entry docs 与校验契约 |
| `WI-054` | backlog 引用 ID 归一化与 verification profile rule mirror | 不新增业务功能；只补规则镜像与校验契约 |
| `WI-055` | checkpoint YAML 字符串兼容性 | 不改业务语义；只处理 `.ai-sdlc/state/checkpoint.yml` 与序列化契约 |
| `WI-056` | coverage audit 历史快照降级与 closeout 汇总入口 | 不重开 owner ledger 或业务 owner；只修 snapshot contract |
| `WI-057` | completed WI task-doc 状态同步与 repo-local task-doc gate | 不改业务实现；只修 `tasks.md` mirror drift |

### 4.6.2 机器可判定 owner ledger

`WI-047` 必须为 `coverage-audit-matrix.md` 中全部剩余未落地行生成一份 row-level owner ledger，至少包含：

- matrix 行号或稳定条目标识
- 条款摘要
- 唯一 owner WI
- non-owner WI
- 前置依赖 artifact
- 当前 gap type

在该 ledger 落地前，`WI-048` 到 `WI-051` 不得声称任何矩阵行已被正式认领或关闭。

#### Owner tie-break 规则

若同一矩阵行同时存在多个 gap type，owner 必须按以下优先级唯一归属：

1. `WI-047`：只要该行无法在当前状态真值、镜像、owner ledger 或 framework gate 约束下被稳定判定，就先归 `WI-047`
2. `WI-048`：若该行仍缺失运行时语义、稳定动作或核心行为实现，则归 `WI-048`
3. `WI-049`：若实现已存在，但主缺口是正式入口、渠道接线或自然语言到 canonical route 的收敛，则归 `WI-049`
4. `WI-050`：若实现和入口均存在，但主缺口是验证、性能、重启、安全、可靠性或交付物验收，则归 `WI-050`
5. `WI-051`：默认不承接矩阵行；只有在 `WI-050` 的 latest-summary 明确 handoff 后，才可承接测试强化残项

若一个条款同时满足多个条件，则以**最高优先级未闭合门禁**为 owner，不得拆成多 owner。

示例：

- `无入口 + 无验证`：若运行时语义已经存在，则先归 `WI-049`；`WI-050` 只能在入口闭环后接手剩余验证
- `无实现 + 无入口`：先归 `WI-048`；只有实现闭环后，入口缺口才允许转交 `WI-049`
- `状态真值不一致 + 无验证`：先归 `WI-047`；只有状态真值稳定后，才允许转入后续 owner

### 4.6.3 依赖图

固定依赖关系如下：

- `WI-047 -> WI-048`
- `WI-047 -> WI-049`
- `WI-048 -> WI-049`
- `WI-048 -> WI-050`
- `WI-049 -> WI-050`
- `WI-049 -> WI-051`
- `WI-050 -> WI-051`
- `WI-051 -> WI-052`
- `WI-052 -> WI-053`
- `WI-053 -> WI-054`
- `WI-054 -> WI-055`
- `WI-055 -> WI-056`
- `WI-056 -> WI-057`

其中：

- `WI-049` 只能消费 `WI-048` 已冻结的 canonical actions / runtime semantics
- `WI-050` 只能验证已由 `WI-048` / `WI-049` 提供的正式 surface
- `WI-051` 只做高耦合接缝测试强化，不承担上游功能或入口定义
- `WI-052` 只关闭 framework contract 与 canonical path discipline，不回改 048-051 的业务 owner 边界
- `WI-053` 只关闭 release entry docs 与 checklist / policy 对齐，不承接打包产物生成
- `WI-054` 只关闭 backlog reference / verification profile mirror，不回改已关闭的 release docs owner 边界
- `WI-055` 只关闭 checkpoint YAML 兼容性，不重开其它 rule surface
- `WI-056` 只关闭历史 coverage audit snapshot 与当前 formal truth 的对账漂移，不回改 047 owner ledger 或 048-055 已关闭条款
- `WI-057` 只关闭 completed work item 的 task-doc status mirror drift，不回改业务执行结果

## 5. 批次执行顺序

固定顺序如下：

1. `WI-047`
2. `WI-048`
3. `WI-049`
4. `WI-050`
5. `WI-051`
6. `WI-052`
7. `WI-053`
8. `WI-054`
9. `WI-055`
10. `WI-056`
11. `WI-057`

不允许跳过 `WI-047` 直接进入产品功能收口，因为状态真值未修复时，矩阵关闭和 work item 收口都会继续漂移。

## 6. 矩阵对账规则

每个 work item 完成后必须做四件事：

1. 更新本批负责条款对应的实现、验证、入口证据
2. 重算未落地条款总数和缺口类型分布
3. 把本批未能关闭的残余条款显式列入 handoff
4. 同步 `latest-summary`、`task-execution-log` 与顶层 `.ai-sdlc` 状态

如果本批回归失败，相关矩阵条目必须保持未落地，或恢复为未落地，不得保留“已关闭”状态。

### 6.1 每个 WI 的最小验证产物

- `WI-047`
  - reconciliation inventory
  - `next_work_item_seq` 重算证据
  - 缺失镜像补齐清单
  - owner ledger
- `WI-048`
  - 动作面 / 运行时语义红绿测试
  - 新增 route 或 service 的 targeted 回归
- `WI-049`
  - Feishu / OpenClaw 正式入口集成测试
  - 自然语言语义到 canonical route 的契约验证
- `WI-050`
  - 性能基准
  - 重启恢复验证
  - 安全 / 审计 / 可观测性验收
  - 最终交付物与测试报告样例
- `WI-051`
  - approval / callback / restart / session spine 高耦合场景矩阵
  - fake / stub / real client seam 契约测试

如果某个 WI 没有产出以上最小验证产物，则不得关闭。

## 7. 风险与控制

### 7.1 最大风险

最大风险不是代码实现，而是：

- formal docs 与运行时实现继续分叉
- 旧 summary 与新 runtime 对同一 work item 给出不同状态
- 入口被示例脚本伪装成正式链路
- 矩阵因为缺少验证或入口证据而被过早关闭

### 7.2 控制手段

- 所有批次都必须先写 canonical spec/plan/tasks
- 每批只关闭自己负责的矩阵行
- 入口必须是主链路运行时 surface，不能拿 example / fixture 充数
- 顶层 `.ai-sdlc` 状态在每一批结束时都要同步

## 8. 设计结论

本轮“覆盖性审计清零”不是一个单一补丁，而是一次受 AI-SDLC 约束的五段式收口：

- 先修状态真值
- 再补纯实现缺口
- 再补正式入口
- 再补验证与非功能闭环
- 最后做高耦合测试强化

后续实现必须以 `WI-047` 为第一执行入口，且任何批次都不得绕开 canonical `specs/` 与 `.ai-sdlc/` 真值链。
