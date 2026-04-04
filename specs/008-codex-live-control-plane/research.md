---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 研究记录：008-codex-live-control-plane

## 方案比较

| 方案 | 结论 | 原因 |
|------|------|------|
| A-Control-Agent 托管本地 `codex app-server --listen stdio://` bridge | 采用 | 与 PRD「A 负责执行，B 负责监管」一致；OpenClaw / Watchdog 继续只接稳定业务接口，不暴露 Codex 内部协议 |
| 直接修改 `~/.codex` 状态文件或 rollout JSONL 注入控制 | 不采用 | 破坏 Codex 自身状态机，难保证线程一致性，也无法形成真实审批回写闭环 |
| 让 OpenClaw 直接连接 Codex app-server | 不采用 | 会把底层协议和本机进程治理泄露到 B 机，扩大外部耦合面，不符合当前仓库边界 |

## 008 与 009 的边界

| 能力 | 008 | 009 |
|------|-----|-----|
| 本地 Codex bridge 生命周期 | 是 | 否 |
| `steer / approval / resume` 打进 live session | 是 | 否 |
| 审计与任务状态回写 | 是 | 否 |
| `SSE / WebSocket` 实时事件流 | 否 | 是 |
| OpenClaw UI 实时订阅 | 否 | 是 |

## 工程约束

- 当前没有现成可复用的远程 app-server 地址，008 必须在 A-Control-Agent 进程内自举本地 Codex bridge。
- 现有 Watchdog / OpenClaw 调用边界已经形成，008 只扩展 A-Control-Agent 内部能力，不扩大外部协议面。
- 由于当前环境的 `ai-sdlc workitem init` 模板缺失，008 的 canonical 文档以手工方式直接落到 `specs/008-codex-live-control-plane/`，不再依赖辅助计划路径作为真值。
