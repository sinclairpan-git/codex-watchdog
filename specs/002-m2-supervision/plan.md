---
related_doc:
  - "codex-watchdog-prd.md"
---

# 实施计划：M2 监管能力

## 目标

交付 stuck 规则引擎（Watchdog 侧）、runtime 侧 steer 写入与持久化、循环失败计数、审计日志模块；不实现飞书通知与完整事件流（留待后续里程碑）。

## 技术栈

来源 `.ai-sdlc/profiles/tech-stack.yml`：Python 3.11+、FastAPI；审计可为追加型 JSONL 或同目录 SQLite 占位，以文件型为主便于测试。

## 架构要点

- **Codex runtime service**：扩展任务存储与 `POST .../steer`；steer 产生 `task_events` 或等价审计行。
- **Watchdog**：`status_analyzer` 读取 runtime 侧任务 JSON（HTTP）或本地快照接口；`action_executor` 在需 steer 时调用 A 的 steer API。
- **审计**：统一 `audit` 模块，字段含 `timestamp`、`project_id`、`action`、`reason`、`source`（watchdog | agent）。

## 阶段产物

| 阶段 | 产出 |
|------|------|
| 设计 | 本目录 `spec.md` / `plan.md` / `research.md` / `data-model.md` |
| 分解 | `tasks.md` |
| 实现 | `src/` 下模块与 `tests/` |

## 宪章响应

决策落在仓库；API 与审计格式以契约与测试校验；需求条目可追溯至 PRD §8、§9.3、§18 M2。
