---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/010-openclaw-integration-spine/spec.md"
  - "specs/011-stable-session-events/spec.md"
  - "specs/014-stable-supervision-evaluation/spec.md"
---

# Stable Session Explanations — 功能规格说明

## 概述

在 `010-openclaw-integration-spine` 冻结最小 stable read/write spine、`011-stable-session-events` 冻结稳定事件面、`012`/`014` 补齐稳定动作之后，当前仍存在一个明显不对称点：

- `why_stuck`
- `explain_blocker`

这两个最小解释语义已经在 adapter 层具备稳定 `ReplyModel(reply_code=stuck_explanation|blocker_explanation)`，但 HTTP stable surface 仍缺位。上层如果不直接嵌入 adapter，就只能自己拼 `facts`、猜 `reply_code`，或者回退到非稳定组合逻辑。

015 的唯一目标固定为：

> 建立 stable session explanation read surface，使 HTTP 调用方能够直接读取 `why_stuck` / `explain_blocker` 的稳定 `ReplyModel`，并确保 API 与 adapter 共享同一 explanation builder，而不是各自复制或临时拼文案。

## 功能需求

- **FR-1501**：015 必须在现有中立 `session_spine` contract 上补齐 explanation read surface；不得把 explanation route 放回 `openclaw` 命名空间，也不得引入新的 legacy/raw explanation API。
- **FR-1502**：015 必须至少提供以下 stable read routes：
  - `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation`
  - `GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation`
- **FR-1503**：上述两个 route 的语义返回值必须继续是已冻结的 `ReplyModel`；其中 `reply_code` 分别固定为 `stuck_explanation` 与 `blocker_explanation`，不得引入第二套 explanation DTO。
- **FR-1504**：`stuck_explanation` 与 `blocker_explanation` 必须继续仅基于 stable read model 与 `FactRecord` 生成；不得新增 raw route 旁路、不得直接读取 legacy `progress / evaluate / approvals / recover / events` 返回体来拼 explanation。
- **FR-1505**：HTTP stable route 与 OpenClaw adapter 必须复用同一 explanation builder；不得在 API 层和 adapter 层各自维护一套 explanation message / fact filter 规则。
- **FR-1506**：015 不新增 `ReplyCode`、`ActionCode`、contract object 字段或 schema 字段；现有 `ReplyModel`、`FactRecord`、`SessionProjection`、`TaskProgressView` 已足以承载 explanation 结果，因此 session spine `contract_version` 与 `schema_version` 保持现状，不因 015 单独推进。
- **FR-1507**：当 control-link 不可达或 A-Control-Agent 返回错误时，015 explanation route 必须继续复用当前 stable read error 语义；不得把 raw upstream envelope 或内部异常栈暴露为 stable explanation payload。
- **FR-1508**：README、getting-started 与 OpenAPI 必须明确把 explanation route 纳入 stable read surface，并说明它们与 adapter intent `why_stuck` / `explain_blocker` 一一对应。
- **FR-1509**：015 必须补齐 explanation route API 测试、shared builder 测试、adapter 非回归测试，以及对既有 `get_session` / `get_progress` / `list_pending_approvals` stable read surface 的非回归验证。

### 用户故事 1：HTTP 调用方直接读取“为什么卡住了”

上层希望通过 HTTP 直接获得稳定 explanation，而不是自行解析 `facts`。

场景 1：调用 `GET /api/v1/watchdog/sessions/repo-a/stuck-explanation`，返回 `ReplyModel(reply_code=stuck_explanation)`。

场景 2：返回体中仍带有 `facts`、`session` 与 `progress`，便于调用方展示或进一步推理。

### 用户故事 2：HTTP 调用方直接读取“当前阻塞点”

上层希望明确知道当前是审批、人类等待还是链路可用性问题，而不是自己二次分类。

场景 1：调用 `GET /api/v1/watchdog/sessions/repo-a/blocker-explanation`，返回 `ReplyModel(reply_code=blocker_explanation)`。

场景 2：当存在 `approval_pending` 时，reply message 与 facts 一致反映该阻塞点。

### 用户故事 3：adapter 与 HTTP 不再漂移

同一项目在 OpenClaw adapter 与 HTTP API 上看到的 explanation 语义应一致。

场景 1：对同一 `project_id`，adapter `why_stuck` 与 HTTP `stuck-explanation` 返回相同 `reply_code` 与同源事实集。

场景 2：`explain_blocker` 也复用同一 explanation builder，而不是一边改过滤规则、另一边漏改。

## 非目标

- 不引入新的 action、receipt、event、history 或 cursor/backfill 协议。
- 不新增 `ExplanationView`、`ExplanationCode` 或其他平行 DTO。
- 不把 015 扩成“完整问答层”或渠道运行时模板系统。
- 不改变 `why_stuck` / `explain_blocker` 既有最小语义，只补齐 stable HTTP surface 与共享 builder。
