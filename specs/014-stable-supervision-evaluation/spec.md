---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/007-prd-alignment/spec.md"
  - "specs/010-runtime-integration-spine/spec.md"
  - "specs/012-stable-recovery-execution/spec.md"
  - "specs/013-stable-action-receipts/spec.md"
---

# Stable Supervision Evaluation — 功能规格说明

## 概述

在 `010-runtime-integration-spine` 冻结 stable session spine、`011-stable-session-events` 冻结稳定事件面、`012-stable-recovery-execution` 冻结真实恢复动作、`013-stable-action-receipts` 冻结稳定收据查询之后，当前仍明显停留在 legacy 形态的核心监管接缝是：

`POST /api/v1/watchdog/tasks/{project_id}/evaluate`

014 的目标不是重做监管系统，而是把这条 **按需触发一次 supervision pass** 的能力，从 legacy DTO / legacy route 收成 **中立 contract + canonical action + 兼容壳**。

014 的唯一目标固定为：

> 建立 stable supervision evaluation contract，使上层可以通过 canonical `WatchdogAction(action_code=evaluate_supervision)` 触发一次最小 supervision evaluation，并获得版本化 `SupervisionEvaluation + WatchdogActionResult`，而不是继续绑定 legacy `/watchdog/tasks/{project_id}/evaluate` 返回体。

## 功能需求

- **FR-1401**：014 必须在现有中立 `session_spine` contract 上新增 supervision evaluation 语义；不得把稳定对象、枚举或 reply code 放进 `feishu` 命名空间，也不得把 `supervision.py` 的现有返回体直接升级成 stable contract。
- **FR-1402**：014 至少冻结以下新增稳定契约元素：`ActionCode.evaluate_supervision`、`ReplyCode.supervision_evaluation`、`SupervisionReasonCode`、`SupervisionEvaluation`，以及 `WatchdogActionResult.supervision_evaluation`。
- **FR-1403**：`SupervisionEvaluation` 必须显式携带 `contract_version` 与 `schema_version`，并继续区分 `thread_id` 与 `native_thread_id`。
- **FR-1404**：`SupervisionEvaluation` 至少包含以下稳定字段：`project_id`、`thread_id`、`native_thread_id`、`evaluated_at`、`reason_code`、`detail`、`current_stuck_level`、`next_stuck_level`、`repo_recent_change_count`、`threshold_minutes`、`should_steer`、`steer_sent`。
- **FR-1405**：014 的 canonical stable write surface 仍必须是 `POST /api/v1/watchdog/actions`；调用方通过提交 `WatchdogAction(action_code=evaluate_supervision)` 触发监督评估，不得再新开一套与 action 模型平行的主写接口。
- **FR-1406**：014 可以提供人类友好的 alias route `POST /api/v1/watchdog/sessions/{project_id}/actions/evaluate-supervision`，但该 alias 只能包装 canonical action route，不得形成第二套动作语义、幂等规则或结果模型。
- **FR-1407**：legacy route `POST /api/v1/watchdog/tasks/{project_id}/evaluate` 必须继续保留并保持基础行为兼容，但它只能作为 compatibility shell 复用稳定 evaluation 内核；它不再承担 stable contract 角色。
- **FR-1408**：stable evaluation 必须继续复用当前仓库已冻结的 `evaluate_stuck(...)` 规则与 repo activity 抑制逻辑；014 不得引入阈值 override、第二套 stuck 规则或新的后台调度策略。
- **FR-1409**：`evaluate_supervision` 成功时必须返回 `WatchdogActionResult(reply_code=supervision_evaluation)`，并在 `supervision_evaluation` 字段中承载稳定评估结果；当评估决定注入 steer 时，`effect=steer_posted`；当评估决定不注入 steer 时，`effect=noop`。
- **FR-1410**：`evaluate_supervision` 必须继续复用既有最小幂等模型：相同 `(action_code, project_id, approval_id?, idempotency_key)` 的重试必须返回同一 `WatchdogActionResult`，且不得重复发起 steer side effect。
- **FR-1411**：当 control-link 不可达、Codex runtime service 返回错误或 steer 调用失败时，014 必须继续复用现有 session spine action error 语义；不得把 raw upstream envelope 或内部异常栈泄漏为 stable contract 字段。
- **FR-1412**：Feishu adapter spine 必须新增最小 write intent `evaluate_supervision`，并映射到稳定 `ReplyModel(reply_code=supervision_evaluation)`；adapter 不得直连 legacy `/watchdog/tasks/{project_id}/evaluate`。
- **FR-1413**：014 必须显式推进 session spine `schema_version`，以反映新增 action code / reply code / evaluation object / result payload 字段；`contract_version` 继续保持 `watchdog-session-spine/v1alpha1`。
- **FR-1414**：014 必须补齐稳定契约测试、evaluation 内核测试、stable API 测试、adapter 测试、receipt / idempotency 非回归，以及 legacy `evaluate` 基础兼容测试。

### 用户故事 1：上层稳定触发一次 supervision evaluation

上层需要主动要求 Watchdog 重新做一次 stuck 判断，并在需要时注入 soft steer，但不希望绑定 legacy `evaluation` dict 的字段形状。

场景 1：调用 `POST /api/v1/watchdog/actions` 并提交 `WatchdogAction(action_code=evaluate_supervision)`，获得稳定 `WatchdogActionResult(reply_code=supervision_evaluation)`。

场景 2：若评估判定需要 steer，则结果中 `effect=steer_posted`，且 `supervision_evaluation.steer_sent=true`。

### 用户故事 2：评估结果可区分“无需 steer”与“已发起 steer”

上层需要判断这次 supervision pass 是真正执行了 soft steer，还是只给出了稳定评估结论。

场景 1：若窗口内仍有文件活动，则 `reason_code=filesystem_activity_recent`，`effect=noop`，`steer_sent=false`。

场景 2：若满足 `stuck_soft` 条件，则 `reason_code=stuck_soft`，`next_stuck_level=2`，`steer_sent=true`。

### 用户故事 3：重复提交不会重复发起 steer

上层或自动化系统需要允许网络重试，而不会因此产生第二次相同 steer。

场景 1：使用相同 `idempotency_key` 重复提交 `evaluate_supervision`，返回相同 `WatchdogActionResult`。

场景 2：同一幂等键不会再次调用 Codex runtime service steer。

### 用户故事 4：legacy evaluate 继续存在，但新接入方不再绑定它

现有依赖 `POST /api/v1/watchdog/tasks/{project_id}/evaluate` 的测试或脚本不能被打断，但新的稳定调用方应迁移到 canonical action。

场景 1：legacy route 仍可调用，且基础 envelope 行为兼容。

场景 2：README / OpenAPI 明确 `legacy evaluate` 只是 compatibility shell；stable contract 以 `WatchdogAction(action_code=evaluate_supervision)` 为准。

## 非目标

- 不引入常驻 supervisor、定时任务、后台轮询或自动重试策略重做。
- 不新增 supervision event stream、evaluation history、cursor/backfill 或 WebSocket。
- 不引入阈值参数化、临时 bypass 标志或第二套 stuck 规则。
- 不改写 `continue_session`、`request_recovery`、`execute_recovery` 已冻结的语义边界。
- 不让 adapter 或其他上层直接调用 legacy `/watchdog/tasks/{project_id}/evaluate`。
