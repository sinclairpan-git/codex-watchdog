---
related_doc:
  - "docs/architecture/coverage-audit-closeout-execution-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml"
  - "specs/048-missing-runtime-semantics-and-action-surface/spec.md"
---

# 实施计划：049-feishu-and-openclaw-entrypoint-closure

## 目标

把 `WI-049` owner 行收敛为稳定、可验证、可被 `WI-050` 消费的正式入口层：Feishu 主入口、OpenClaw compatibility 入口，以及自然语言到 canonical route 的统一映射。

## 架构摘要

- **Entrypoint only, not semantics rewrite**：049 只把 Feishu / OpenClaw / natural-language 接到 048 已冻结的 canonical route，不修改状态机、动作面、审批真相或 `Memory Hub` precedence。
- **Feishu primary, OpenClaw compatibility-only**：新主链路能力优先从 Feishu 入口落地；OpenClaw 只能消费共享 intent catalog / routing / route binding。
- **One intent catalog, many channels**：自然语言短指令和显式 intent 都必须先归一到共享 intent catalog，再映射到 stable query/action surface，避免多入口多套语义。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
| --- | --- | --- |
| Formal docs / task plan | `specs/049-feishu-and-openclaw-entrypoint-closure/*` | 冻结 049 owner 行范围、任务拆解、执行日志与 handoff |
| Feishu primary command gateway | `src/watchdog/services/feishu_control/service.py`、`src/watchdog/api/feishu_control.py` | 扩展 Feishu 主入口，支持查询、控制、bootstrap 与 canonical routing |
| Shared entry intent catalog | `src/watchdog/services/adapters/openclaw/intents.py`、新增 `src/watchdog/services/entrypoints/*` | 维护显式 intent 与自然语言短指令到 canonical route 的统一映射 |
| OpenClaw compatibility entry | `src/watchdog/services/adapters/openclaw/adapter.py`、`src/watchdog/api/openclaw_responses.py` | 让 OpenClaw 继续可用，但只消费共享 mapping / routing / canonical route |
| Route / routing contract tests | `tests/test_watchdog_feishu_control.py`、`tests/test_watchdog_openclaw_adapter.py`、`tests/integration/test_openclaw_integration_spine.py` | 锁定主入口与兼容入口 contract |

## 边界纪律

- 049 不得新增 048 未定义的新动作语义、状态枚举或审批真相。
- Feishu 必须是 primary control plane；OpenClaw 只能保留 compatibility-only 读写接口。
- 049 的入口证据必须是 live route 或主链路实际消费 surface，不能用 `examples/` 或 summary 冒充。
- 049 可以新增共享 intent / routing helper，但不能让 Feishu 与 OpenClaw 各自维护独立语义分支。
- 049 不得关闭 `WI-050` 的性能 / 重启 / 安全 / 验收条款，也不得关闭 `WI-051` 的高耦合 hardening 条款。

## 测试计划

- `tests/test_watchdog_feishu_control.py`
- `tests/test_watchdog_openclaw_adapter.py`
- `tests/integration/test_openclaw_integration_spine.py`

## Review Gate

- `docs_baseline_ref` 必须按 `spec.md` 中冻结的 hash recipe 生成；
- `.ai-sdlc/state/checkpoint.yml` 必须切到 `049-feishu-and-openclaw-entrypoint-closure`；
- `project-state.yaml.next_work_item_seq` 必须更新为 `50`；
- `current_branch` 必须 pin 到 `codex/049-feishu-and-openclaw-entrypoint-closure`；
- `WI-049` 只允许消费 `WI-048 runtime semantics baseline` 与 `canonical route contract`。

## 交付物

- `specs/049-feishu-and-openclaw-entrypoint-closure/spec.md`
- `specs/049-feishu-and-openclaw-entrypoint-closure/plan.md`
- `specs/049-feishu-and-openclaw-entrypoint-closure/tasks.md`
- `.ai-sdlc/work-items/049-feishu-and-openclaw-entrypoint-closure/*`
- 049 冻结后的 Feishu / OpenClaw / natural-language 入口红绿测试与 targeted integration evidence
