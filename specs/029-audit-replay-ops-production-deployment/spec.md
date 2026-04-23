---
related_doc:
  - "docs/architecture/codex-watchdog-full-product-loop-design.md"
  - "specs/028-webhook-response-api-reference-runtime/spec.md"
---

# 审计、回放、运维与生产部署 — 功能规格说明

## 概述

`029-audit-replay-ops-production-deployment` 是完整产品闭环中的 `WI-6`。它的目标是把当前“能跑”的 A/B 部署、公网接入、日志与告警，补成可长期运营的生产态闭环。

## 功能需求

- **FR-2901**：029 必须把 canonical decision、approval、delivery、receipt 与 response 统一纳入可查询审计面。
- **FR-2902**：029 必须提供 replay / forensic 工具，允许按：
  - `session_id`
  - `decision_id`
  - `approval_id`
  - `envelope_id`
  - `receipt_id`
  回放关键链路。
- **FR-2903**：029 必须冻结公网生产化基线，包括：
  - A/B 固定入口或受控公网方案
  - token / secret 管理与轮换
  - webhook 签名校验
  - install / upgrade / rollback 标准流程
- **FR-2904**：029 必须补齐 metrics / health / alerts，至少覆盖：
  - `delivery_failed`
  - `blocked_too_long`
  - `approval_pending_too_long`
  - `recovery_failed`
  - `mapping_incomplete`
- **FR-2905**：029 必须提供 operator runbook，至少覆盖：
  - A/B 启停
  - 公网入口失效
  - 密钥轮换
  - replay / forensic
  - 死信处理
- **FR-2906**：029 必须让部署与升级不再依赖临时 quick tunnel 或单次人工操作说明。
- **FR-2907**：029 必须补齐生产化验证，至少覆盖：
  - install / upgrade
  - restart / restore
  - alerting path
  - replay path
- **FR-2908**：029 不得反向修改前 `024-028` 已冻结的核心协议与职责边界；若发现缺口，应以缺陷或后续 WI 形式处理，而不是在 029 中重写核心契约。
- **FR-2909**：029 必须把服务启动、重启与开机自启收成可执行资产，而不只是文字说明。至少应提供：
  - 一个标准启动脚本
  - 一个标准安装/注册脚本
  - 一个可审阅的守护进程模板（例如 macOS `launchd`）
- **FR-2910**：029 的 runbook 必须明确 resident system 的故障处理边界：
  - 瞬时网络或宿主不可达时，优先 retry / backoff / alert
  - `context_critical` 类问题优先走 canonical recovery 链路恢复
  - 持续外部故障、额度耗尽、权限不足等不可自愈问题必须进入显式告警或人工升级

### 用户故事 1：系统可以被长期运营，而不是只能一次性跑通

场景 1：服务升级后，session spine、decision records、outbox 与 delivery 状态保持可恢复。

场景 2：A/B 公网通信入口失效时，operator 能按 runbook 恢复，而不是依赖临时人工记忆。

场景 3：机器重启后，Watchdog 能按标准启动脚本与守护进程模板自动拉起；若自动恢复失败，operator 也有明确的一键重启方式。

### 用户故事 2：问题发生后可以审计与回放

场景 1：某次自动决策引发异常，operator 可以按 `decision_id` 回放证据链。

场景 2：某次 envelope 丢失或重复，operator 可以按 `envelope_id` 与 `receipt_id` 查清事实。

## 非目标

- 不重写 `024-028` 的核心契约。
- 不把运维面做成新的业务内核。
- 不引入飞书业务语义或宿主策略逻辑。
- 不把关键恢复责任转交给 Feishu 记忆或人工口头流程。
