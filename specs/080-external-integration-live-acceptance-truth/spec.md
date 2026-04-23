# Spec：080-external-integration-live-acceptance-truth

## 背景

`WI-079` 已完成 framework state resume-pack 的 canonical sync，当前 repo-local `ai_sdlc` 主干已恢复到一致状态。继续审查下一张工单时，新的风险点不再是运行时代码漂移，而是 **真实环境联调口径的真值保护仍然偏弱**：

- [`docs/operations/external-integration-live-acceptance.md`](/Users/sinclairpan/project/codex-watchdog/docs/operations/external-integration-live-acceptance.md) 已经写出 fail-closed 规则与两种推荐结论口径，但 repo-local docs contract 只验证了 runbook 覆盖 Feishu / provider / memory / smoke 命令，没有把“不得把外部平台 blocker 写成仓库已自动闭环”的真值边界纳入测试；
- [`docs/framework-defect-backlog.zh-CN.md`](/Users/sinclairpan/project/codex-watchdog/docs/framework-defect-backlog.zh-CN.md) 里的 `FD-004` 仍停留在“待补 validator、CLI gate 与回归测试”，与 `WI-079` 已完成的实际状态不一致；
- 如果后续文档继续漂移，仓库可能重新出现“repo 内 contract 已落地”与“真实环境接线已验收通过”被混写的风险。

因此 `WI-080` 的目标不是重开任何 Feishu / provider / Memory 功能，而是把 **live acceptance 的 truth boundary** 冻结成 repo-local docs contract，并同步 formal backlog 口径。

## 范围

### In Scope

- 强化 `external-integration-live-acceptance` runbook 的真值边界表述；
- 扩展 repo-local docs contract，要求 runbook 明确区分“repo 内 contract 已落地”与“真实环境仍被外部平台阻断”；
- 同步 `tests/test_long_running_autonomy_doc_contracts.py`，把新的 truth-boundary contract 纳入回归；
- 更新 framework defect backlog 中 `FD-004` 的状态描述，使其与 `WI-079` 的完成态一致；
- 为 `WI-080` 补齐 `spec / plan / tasks / task-execution-log` 以及 `.ai-sdlc/work-items/080-*` formal mirror。

### Out of Scope

- 不新增或修改任何 Watchdog 运行时行为；
- 不接入真实 Feishu 组织、真实公网域名、证书、密钥轮换或外部 provider 凭证；
- 不把 live acceptance runbook 升格为 release gate 或 production acceptance gate；
- 不重开 `WI-075` / `WI-076` / `WI-077` 已经完成的 smoke harness 与 Feishu control runtime 实现。

## Formal Source

- `docs/operations/external-integration-live-acceptance.md`
- `src/watchdog/validation/docs_contracts.py`
- `tests/test_long_running_autonomy_doc_contracts.py`
- `docs/framework-defect-backlog.zh-CN.md`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `.ai-sdlc/project/config/project-state.yaml`

## 非 Owner 约束

- **FR-8001**：`WI-080` 只收口 live acceptance 文档真值与 formal backlog 同步，不得夹带任何运行时代码改动。
- **FR-8002**：repo-local docs contract 只能冻结文档中已经确定的 truth boundary，不得发明新的外部验收流程或新的 operator 角色分工。
- **FR-8003**：`FD-004` 的状态修正必须反映 `WI-079` 已落地事实，不得改写其 defect 现象、根因或成功标准。

## 功能需求

- **FR-8004**：`docs/operations/external-integration-live-acceptance.md` 必须明确写明，它不声明外部组织安装、域名、证书、密钥轮换、凭证发放已经自动完成。
- **FR-8005**：repo-local docs contract 必须要求 live acceptance runbook 保留“release gate 与 live acceptance 必须同时成立”以及“两种推荐结论口径”，防止后续文档把真实环境 blocker 与 repo 内 contract drift 混写。
- **FR-8006**：`tests/test_long_running_autonomy_doc_contracts.py` 必须对新的 truth-boundary contract 建立显式存在性断言。
- **FR-8007**：`docs/framework-defect-backlog.zh-CN.md` 中 `FD-004` 的当前状态必须更新为 `WI-079` 已完成，而不是继续描述待补项。
- **FR-8008**：`WI-080` formal closeout 后，`.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/state/resume-pack.yaml`、`.ai-sdlc/project/config/project-state.yaml` 与当前分支必须共同指向 `080-external-integration-live-acceptance-truth`，并把 `next_work_item_seq` 前滚到 `81`。

## 验证要求

- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
