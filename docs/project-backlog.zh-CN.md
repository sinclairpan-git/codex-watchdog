# Project Backlog

> 项目级 backlog，用于记录已确认但暂不启动的产品或工程增强事项。
>
> 说明：
> - 本文件记录项目后续工作，不记录框架违约。
> - 框架违约仍统一记录在 `docs/framework-defect-backlog.zh-CN.md`。

## BL-2026-04-06-001 前端强化后执行测试模块强化
- 状态: completed
- 优先级: 高
- 进入时机: 当前前端 / OpenClaw-facing 交互面强化完成并合入主线后，再启动独立 work item；在此之前不与前端改动并行推进。
- 背景: 023 合入过程中，`Codex bridge -> approval callback -> restart restore -> session spine` 这条高耦合接缝的问题不是一次性在本地暴露，而是通过多轮 review 才逐步暴露，说明测试虽然已经补强，但仍需要一次专门的体系化强化，而不是继续依赖“来一条问题补一条回归”。
- 目标: 将这条接缝的验证方式从“按 review comment 补点状回归”升级为“按场景矩阵覆盖整条状态机”。
- 范围:
  - callback send failure、deferred retry、delivered replay guard 的稳定回归
  - restart restore、legacy persisted row、numeric request id、approval method recovery 的恢复链路测试
  - session spine 的 project-scoped approval filtering、deferred slice、fallback slice 的显式契约测试
  - fake client / stub 与真实 `AClient` 接口签名和过滤语义对齐
  - targeted suite、full suite、seam smoke 三层验证入口的梳理与固定
- 非目标:
  - 不在该事项中引入飞书 / OpenClaw runtime UI 自动化
  - 不把前端强化与测试强化混成同一个 work item
  - 不在当前 backlog 条目里直接启动实现
- 建议产出:
  - 一个独立 formal work item 的 `spec.md`、`plan.md`、`tasks.md`
  - 一份高耦合接缝场景矩阵
  - 一组覆盖恢复链路和过滤契约的回归测试
  - 一组约束 fake / stub 漂移的契约测试
- 完成标准:
  - 已知高耦合接缝具备显式场景矩阵，且矩阵项与测试一一映射
  - 新增或扩展 `AClient` 读接口参数时，测试替身会因签名或过滤语义不一致而直接失败
  - approval / callback / restart 三段链路存在至少一条跨重启回归测试
  - 全量测试保持稳定通过
- 候选落点:
  - `tests/test_codex_app_server_bridge.py`
  - `tests/test_a_control_agent_control_flow.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/integration/test_openclaw_integration_spine.py`
  - 必要时补充一个专门的场景矩阵文档
