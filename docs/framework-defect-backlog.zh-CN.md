# Framework Defect Backlog

## FD-2026-04-05-001 宿主执行链未在用户明确要求后回切到仓库文档先行真值
- 现象: 用户明确要求“先归档到项目文档，再拆解、设计、任务拆分，最后才能 coding”后，执行流仍继续推进到实现准备，并把计划写到非 canonical 路径。
- 触发场景: 在本仓库讨论 Codex 对接方案并收到流程硬约束后，宿主仍按 superpowers 的 planning / execution workflow 推进，先发生实施准备，随后又把计划落到 docs/superpowers/plans 一类技能默认位置。
- 影响范围: 破坏 design / decompose -> verify -> execute 的法定顺序，误导用户认为计划已获得实施授权，并把文档写到非仓库真值路径。
- 根因分类: 宿主 workflow 优先级覆盖项目级框架约束，且在真正落动作前缺少基于仓库阶段真值的路径归一化。
- 未来杜绝方案摘要: 当用户给出项目级硬约束时，先以仓库 canonical 阶段真值重置当前动作；superpowers 计划只能作为辅助输入，不得直接决定保存路径或实施授权。
- 建议改动层级: rule / workflow / tool / eval
- prompt / context: 在用户说出“先文档”“先 spec-plan-tasks”“不允许直接 coding”“不要写到 superpowers”时，将其提升为 execute 禁止信号，并要求先确认 canonical 文档路径。
- rule / policy: 在宿主适配层明确“项目级硬约束优先于 skills 默认值”，并显式声明 docs/superpowers 下的计划不是仓库执行真值。
- middleware: 在 action planner 中增加 path-normalization hook；当仓库存在 specs/ 与 .ai-sdlc/project/config/project-state.yaml 时，禁止把技能默认输出目录作为 canonical 目标。
- workflow: design / decompose 前必须先确认目标文档位于 specs/<WI>/ 或项目明确指定目录；未确认前不得进入任何产品代码编辑。
- tool: 在写计划或记录违约前，先运行只读检查输出 canonical path、current_stage、pending gate；目标路径不合规则中止写入。
- eval: 增加“用户明确要求先文档、禁止 coding、禁止写入 superpowers 目录”的对抗样例，要求代理只能停留在文档阶段。
- 风险等级: 高
- 可验证成功标准: 同类场景下首次写入即落到 canonical 文档目录，且在用户未显式授权 execute 前不会编辑产品代码。
- 是否需要回归测试补充: 需要

## FD-2026-04-05-002 Framework backlog 发现与缺省校验存在漏斗
- 现象: 排查框架违约时，最初没有直接定位到 canonical framework backlog，并错误创建了 docs/backlog.md；同时 `python -m ai_sdlc verify constraints` 对缺少 docs/framework-defect-backlog.zh-CN.md 不报 BLOCKER。
- 触发场景: 仓库已经完成 `.ai-sdlc` formal bootstrap，但尚未存在 canonical framework backlog 文件；代理按通用“backlog”直觉搜索，而不是先按框架真值定位主 backlog。
- 影响范围: 框架违约可能被写到错误文件名并绕过主 backlog，导致历史问题不可追踪、校验不拦截、用户需要反复提醒。
- 根因分类: 规则发现链缺口，校验器对 canonical backlog 缺失采取“文件不存在则跳过”策略，且宿主没有强制先读 rule 真值。
- 未来杜绝方案摘要: 将“框架违约待办”从可选发现改成强制发现；首次命中时自动创建 canonical backlog 模板，并在 verify 中对缺失文件给出显式告警或 blocker。
- 建议改动层级: rule / middleware / workflow / tool / eval
- prompt / context: 当用户提到 backlog、违约、框架缺陷、记录到待办时，优先解析为 docs/framework-defect-backlog.zh-CN.md，而不是通用 backlog 文件。
- rule / policy: 在规则文档与适配提示中明确“框架 backlog 不等于项目通用 backlog；未存在时应创建 canonical 文件，而不是自定义新文件名”。
- middleware: 在约束发现器中加入 canonical backlog locator；发现 `.ai-sdlc/project/config/project-state.yaml` 时自动暴露主 backlog 路径。
- workflow: 处理框架违约的固定步骤必须包含“先读 canonical 路径 -> 若缺失则创建模板 -> 追加条目 -> verify constraints”。
- tool: 调整 `verify_constraints`，对已初始化 AI-SDLC 项目缺少 docs/framework-defect-backlog.zh-CN.md 时至少输出显式 warning；命中违约记录流程时可升级为 blocker。
- eval: 新增“仓库已初始化但 backlog 文件尚不存在”的场景，要求代理创建 canonical backlog，而不是写 docs/backlog.md。
- 风险等级: 高
- 可验证成功标准: 在同类仓库首次记录框架违约时，系统总是创建并写入 docs/framework-defect-backlog.zh-CN.md，且 verify 输出能显式发现缺省文件问题。
- 是否需要回归测试补充: 需要

## FD-2026-04-07-003 已知 canonical 文档路径存在时仍回退到 skill 默认 spec 目录
- 现象: 在已经确认本仓库的跨 work-item 总设计应落到 `docs/architecture/`、单 work item formal 文档应落到 `specs/<work-item>/` 之后，宿主仍再次口头提出把总设计写入 `docs/superpowers/specs/2026-04-07-full-product-loop-design.md`。
- 触发场景: 讨论“完整产品闭环”的总设计冻结结论后，宿主沿用 `brainstorming` skill 的默认保存路径来描述下一步设计文档落点，而没有先按仓库既有 canonical 结构做路径归一化。
- 影响范围: 即使尚未真正写文件，也会再次把项目真值目录说错，制造“总设计到底写在 skill 默认目录还是项目架构目录”的歧义；用户需要反复纠偏，且会削弱此前违约记录的约束力。
- 根因分类: 已知规则未被执行前门禁吸收；宿主把 skill 默认输出路径当作可直接复用的建议，而不是先通过仓库 canonical path policy 过滤。该问题与 `FD-2026-04-05-001` 同源，但说明“用户已纠偏过一次”仍不足以形成稳定抑制。
- 未来杜绝方案摘要: 将“提及任何拟保存路径”本身纳入 canonical path gate；只要仓库已存在 `docs/architecture/` 与 `specs/` 的正式真值结构，就禁止在提案、计划、设计摘要中再次说出 `docs/superpowers/specs` 作为正式落点。
- 建议改动层级: rule / middleware / workflow / eval
- prompt / context: 当用户讨论“总设计”“架构冻结”“正式 spec”“规范目录”“不要写到 superpowers”时，必须先从仓库真值推导候选路径，再允许输出任何具体文件名。
- rule / policy: 明确区分三类文档落点：
  - `docs/architecture/` 只承载跨多个 work item 的总设计与冻结架构。
  - `specs/<work-item>/` 只承载单 work item 的 formal spec / plan / tasks。
  - `docs/superpowers/` 仅允许保存 skill 自身的通用过程产物，不得作为本项目的正式设计真值目录。
- middleware: 在回应中出现“写入 <path>”或“保存到 <path>”前，强制执行 canonical path classifier；若候选路径命中 `docs/superpowers/` 且仓库存在项目级正式目录，则直接改写为 canonical 目录或要求重新分类。
- workflow: 任何 design/doc handoff 都必须先做“文档类型 -> canonical 目录”判定，再给出下一步文件路径；路径未归类前，不得输出具体保存位置。
- tool: 增加只读 path-check 步骤，至少检查：
  - 是否存在 `docs/architecture/`
  - 是否存在 `specs/`
  - 当前文档是“总设计”还是“单 WI formal 文档”
  - 候选路径是否命中禁止目录
- eval: 增加回归样例：
  - 仓库已存在 `docs/architecture/` 与 `specs/`，用户追问“为什么又写到 superpowers”时，代理必须给出 canonical 路径并记录违约，而不是再次沿用 skill 默认路径。
  - 同一线程中已被用户纠偏过一次后，后续回答不得再次提出 `docs/superpowers/specs` 作为正式落点。
- 风险等级: 高
- 可验证成功标准:
  - 在同类仓库里，涉及“总设计”“架构冻结”“正式 spec”的文件提案时，输出路径始终落到 `docs/architecture/` 或 `specs/<work-item>/`。
  - 即使 skill 默认说明仍指向 `docs/superpowers/specs`，宿主输出也不会复述该路径为项目正式落点。
  - 当用户指出“这个问题已经出现过很多次”时，系统能直接关联既有 defect 条目并输出根因与杜绝方案，而不是再次发生同类路径漂移。
- 是否需要回归测试补充: 需要
