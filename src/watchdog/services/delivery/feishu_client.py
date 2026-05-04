from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import httpx
from pydantic import ValidationError

from watchdog.services.delivery.envelopes import (
    ApprovalEnvelope,
    DecisionEnvelope,
    NotificationEnvelope,
)
from watchdog.services.delivery.models import DeliveryAttemptResult
from watchdog.services.delivery.store import DeliveryOutboxRecord
from watchdog.settings import Settings


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _compact_whitespace(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def _truncate_text(value: str, *, limit: int) -> str:
    normalized = _compact_whitespace(value)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 1, 0)].rstrip() + "…"


@dataclass(slots=True)
class _TenantToken:
    value: str
    expires_at: datetime


class FeishuAppDeliveryClient:
    def __init__(
        self,
        *,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._tenant_token: _TenantToken | None = None

    def configured(self) -> bool:
        return all(
            [
                str(self._settings.feishu_base_url or "").strip(),
                str(self._settings.feishu_app_id or "").strip(),
                str(self._settings.feishu_app_secret or "").strip(),
            ]
        )

    def deliver_record(self, record: DeliveryOutboxRecord) -> DeliveryAttemptResult:
        payload = dict(record.envelope_payload)
        model_map = {
            "decision": DecisionEnvelope,
            "notification": NotificationEnvelope,
            "approval": ApprovalEnvelope,
        }
        model = model_map.get(str(payload.get("envelope_type")))
        if model is None:
            return DeliveryAttemptResult(
                envelope_id=record.envelope_id,
                delivery_status="delivery_failed",
                accepted=False,
                failure_code="unsupported_envelope_type",
            )
        try:
            envelope = model.model_validate(payload)
        except ValidationError:
            return DeliveryAttemptResult(
                envelope_id=record.envelope_id,
                delivery_status="delivery_failed",
                accepted=False,
                failure_code="invalid_envelope_payload",
            )
        return self.deliver_envelope(envelope)

    def deliver_envelope(
        self,
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> DeliveryAttemptResult:
        if not self.configured():
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="delivery_failed",
                accepted=False,
                failure_code="feishu_not_configured",
            )
        receive_id, receive_id_type = self._resolve_receive_target(envelope)
        if not receive_id or not receive_id_type:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="delivery_failed",
                accepted=False,
                failure_code="feishu_not_configured",
            )
        try:
            tenant_token = self._tenant_access_token()
        except httpx.TimeoutException:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_timeout",
            )
        except httpx.HTTPStatusError as exc:
            return self._classify_http_status_failure(
                envelope_id=envelope.envelope_id,
                status_code=exc.response.status_code,
            )
        except httpx.RequestError:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_error",
            )
        except ValueError:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
            )

        url = (
            f"{str(self._settings.feishu_base_url).rstrip('/')}"
            "/open-apis/im/v1/messages"
        )
        body = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps(
                {"text": self._render_text(envelope)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        try:
            with httpx.Client(
                timeout=self._settings.http_timeout_s,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    url,
                    params={"receive_id_type": receive_id_type},
                    headers={
                        "Authorization": f"Bearer {tenant_token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json=body,
                )
        except httpx.TimeoutException:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_timeout",
            )
        except httpx.RequestError:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_error",
            )
        if 200 <= response.status_code < 300:
            return self._classify_success(envelope_id=envelope.envelope_id, response=response)
        return self._classify_http_status_failure(
            envelope_id=envelope.envelope_id,
            status_code=response.status_code,
        )

    def _tenant_access_token(self) -> str:
        current = self._tenant_token
        now = datetime.now(UTC)
        if current is not None and current.expires_at > now + timedelta(seconds=30):
            return current.value
        url = (
            f"{str(self._settings.feishu_base_url).rstrip('/')}"
            "/open-apis/auth/v3/tenant_access_token/internal"
        )
        with httpx.Client(
            timeout=self._settings.http_timeout_s,
            transport=self._transport,
            trust_env=False,
        ) as client:
            response = client.post(
                url,
                json={
                    "app_id": str(self._settings.feishu_app_id),
                    "app_secret": str(self._settings.feishu_app_secret),
                },
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            response.raise_for_status()
        body = response.json()
        if int(body.get("code", 1)) != 0:
            raise ValueError("feishu tenant token rejected")
        token = str(body.get("tenant_access_token") or "").strip()
        if not token:
            raise ValueError("feishu tenant token missing")
        expire_seconds = int(body.get("expire") or 7200)
        self._tenant_token = _TenantToken(
            value=token,
            expires_at=now + timedelta(seconds=max(expire_seconds, 60)),
        )
        return token

    def _resolve_receive_target(
        self,
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> tuple[str | None, str | None]:
        receive_id = str(
            getattr(envelope, "receive_id", None) or self._settings.feishu_receive_id or ""
        ).strip()
        receive_id_type = str(
            getattr(envelope, "receive_id_type", None)
            or self._settings.feishu_receive_id_type
            or ""
        ).strip()
        if not receive_id or not receive_id_type:
            return (None, None)
        return (receive_id, receive_id_type)

    @staticmethod
    def _classify_http_status_failure(
        *,
        envelope_id: str,
        status_code: int,
    ) -> DeliveryAttemptResult:
        return DeliveryAttemptResult(
            envelope_id=envelope_id,
            delivery_status=(
                "retryable_failure" if status_code in {408, 429} or status_code >= 500 else "delivery_failed"
            ),
            accepted=False,
            failure_code=f"http_{status_code}",
            status_code=status_code,
        )

    @staticmethod
    def _classify_success(
        *,
        envelope_id: str,
        response: httpx.Response,
    ) -> DeliveryAttemptResult:
        try:
            body = response.json()
        except ValueError:
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        if int(body.get("code", 1)) != 0:
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        data = body.get("data")
        if not isinstance(data, dict):
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        message_id = str(data.get("message_id") or "").strip()
        if not message_id:
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        return DeliveryAttemptResult(
            envelope_id=envelope_id,
            delivery_status="delivered",
            accepted=True,
            receipt_id=message_id,
            received_at=_iso_z(datetime.now(UTC)),
            status_code=response.status_code,
        )

    @classmethod
    def _render_text(
        cls,
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> str:
        if isinstance(envelope, ApprovalEnvelope):
            return cls._render_approval_text(envelope)
        if isinstance(envelope, DecisionEnvelope):
            return cls._render_decision_text(envelope)
        if envelope.notification_kind == "decision_result":
            return cls._render_decision_notification_text(envelope)
        if envelope.notification_kind == "session_directory_summary":
            return cls._render_session_directory_notification_text(envelope)
        return cls._render_notification_text(envelope)

    @staticmethod
    def _display_session_id(session_id: str) -> str:
        normalized = str(session_id or "").strip()
        return normalized.removeprefix("session:") or normalized

    @staticmethod
    def _base_lines(
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> list[str]:
        return [
            f"项目：{envelope.project_id}",
            f"会话：{FeishuAppDeliveryClient._display_session_id(envelope.session_id)}",
        ]

    @staticmethod
    def _humanize_action(action_name: str | None) -> str:
        normalized = str(action_name or "").strip()
        action_labels = {
            "continue_session": "继续当前任务",
            "execute_recovery": "执行恢复流程",
            "request_recovery": "查看恢复建议",
            "pause_session": "暂停当前任务",
            "resume_session": "恢复当前任务",
            "summarize_session": "生成任务摘要",
            "force_handoff": "人工接管当前任务",
            "handoff_to_human": "人工接管当前任务",
            "retry_with_conservative_path": "按保守路径重试",
        }
        if not normalized:
            return "当前操作"
        return action_labels.get(normalized, normalized.replace("_", " "))

    @classmethod
    def _humanize_decision_result(cls, decision_result: str, action_name: str | None) -> str:
        action_label = cls._humanize_action(action_name)
        normalized = str(decision_result or "").strip()
        decision_labels = {
            "auto_execute_and_notify": f"已自动执行「{action_label}」",
            "require_user_decision": f"需要人工确认后再执行「{action_label}」",
            "block_and_alert": f"已阻断「{action_label}」并发出提醒",
        }
        return decision_labels.get(normalized, f"{normalized or '已更新'}「{action_label}」")

    @staticmethod
    def _humanize_reason(reason: str | None) -> str:
        normalized = str(reason or "").strip()
        if not normalized:
            return ""
        phrase_map = {
            "session requires explicit human decision": "当前会话需要人工明确确认。",
            "recovery execution requires explicit human decision": "恢复操作需要人工明确确认。",
            "registered action and complete evidence": "动作已登记，且证据完整。",
        }
        if normalized in phrase_map:
            return phrase_map[normalized]
        parts: list[str] = []
        label_map = {
            "phase": "当前处于 {value} 阶段",
            "context": "上下文压力为 {value}",
            "stuck": "卡点等级为 {value}",
            "files": "涉及文件 {value}",
        }
        for raw_part in normalized.split(";"):
            part = raw_part.strip()
            if not part:
                continue
            key, separator, value = part.partition("=")
            if not separator:
                parts.append(part)
                continue
            template = label_map.get(key.strip())
            if template is None:
                parts.append(part)
                continue
            parts.append(template.format(value=value.strip()))
        if parts:
            return "；".join(parts)
        return normalized

    @staticmethod
    @staticmethod
    def _next_step_is_delivery_safe(message: str) -> bool:
        if not message:
            return False
        if len(message) > 220:
            return False
        unsafe_markers = (
            "::git-",
            "@Codex review",
            "GitHub Actions",
            "merge commit",
            "Pull Request",
            "PR #",
            "后续任务：",
            "项目总目标：",
            "当前分支目标：",
            "当前进度：",
        )
        if any(marker in message for marker in unsafe_markers):
            return False
        if message.count("`") >= 4:
            return False
        return True

    @classmethod
    def _render_next_step(
        cls,
        action_args: dict[str, object] | None,
        *,
        action_name: str | None = None,
    ) -> str:
        if str(action_name or "").strip() == "post_operator_guidance":
            return ""
        if not isinstance(action_args, dict):
            return ""
        message = str(action_args.get("message") or "").strip()
        if not message:
            return ""
        message = _compact_whitespace(message)
        message = re.sub(r"(?:\[\s*steer:[^\]]+\]\s*)+", "", message)
        message = re.sub(
            r"(?:下一步建议：\s*)+",
            "下一步建议：",
            message,
        )
        message = re.sub(
            r"(?:建议下一步：\s*)+",
            "建议下一步：",
            message,
        )
        message = re.sub(
            r"(?:\[steer:[^\]]+\]\s*下一步建议：继续推进\s*)+",
            "",
            message,
        )
        message = re.sub(
            r"(?:下一步建议：继续推进\s*){2,}",
            "下一步建议：继续推进 ",
            message,
        )
        message = re.sub(
            r"(?:建议下一步：继续推进\s*){2,}",
            "建议下一步：继续推进 ",
            message,
        )
        message = re.sub(r"(?:并优先验证最近改动[。.,，]*)+", "并优先验证最近改动。", message)
        message = re.sub(r"(?:如果无阻塞，请立即继续执行。?)+", "", message)
        for prefix in ("下一步建议：", "建议下一步："):
            if message.startswith(prefix):
                message = message[len(prefix) :].strip()
                break
        message = message.strip(" |；。，,")
        if not cls._next_step_is_delivery_safe(message):
            return ""
        return message

    @staticmethod
    def _render_key_facts(facts: list[dict[str, object]] | None) -> str:
        if not isinstance(facts, list):
            return ""
        summaries: list[str] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            summary = str(fact.get("summary") or fact.get("detail") or fact.get("fact_code") or "").strip()
            if not summary or summary in summaries:
                continue
            summaries.append(summary)
            if len(summaries) >= 3:
                break
        return "；".join(summaries)

    @classmethod
    def _render_approval_text(cls, envelope: ApprovalEnvelope) -> str:
        lines = [
            "Watchdog 需要你确认一项操作",
            *cls._base_lines(envelope),
            f"待确认操作：{cls._humanize_action(envelope.requested_action)}",
        ]
        summary = str(envelope.summary or "").strip()
        if summary:
            lines.append(f"背景说明：{summary}")
        reason = cls._humanize_reason(envelope.reason or envelope.why_escalated)
        if reason:
            lines.append(f"原因：{reason}")
        next_step = cls._render_next_step(
            envelope.requested_action_args,
            action_name=envelope.requested_action,
        )
        if next_step:
            lines.append(f"建议下一步：{next_step}")
        key_facts = cls._render_key_facts(envelope.facts)
        if key_facts:
            lines.append(f"关键依据：{key_facts}")
        lines.append('你现在可以这样干预：回复“批准”、“拒绝”或“直接执行”')
        return "\n".join(lines)

    @classmethod
    def _render_decision_text(cls, envelope: DecisionEnvelope) -> str:
        lines = [
            "Watchdog 自动决策更新",
            *cls._base_lines(envelope),
            f"自动决策：{cls._humanize_decision_result(envelope.decision_result, envelope.action_name)}",
        ]
        decision_reason = str(envelope.decision_reason or envelope.reason or "").strip()
        if decision_reason:
            lines.append(f"决策依据：{decision_reason}")
        next_step = cls._render_next_step(
            envelope.action_args,
            action_name=envelope.action_name,
        )
        if next_step:
            lines.append(f"建议下一步：{next_step}")
        key_facts = cls._render_key_facts(envelope.facts)
        if key_facts:
            lines.append(f"关键依据：{key_facts}")
        lines.append('你现在可以这样干预：回复“状态”查看详情，或回复“人工接管”')
        return "\n".join(lines)

    @classmethod
    def _render_decision_notification_text(cls, envelope: NotificationEnvelope) -> str:
        lines = [
            "Watchdog 自动决策更新",
            *cls._base_lines(envelope),
            f"自动决策：{cls._humanize_decision_result(envelope.decision_result or '', envelope.action_name)}",
        ]
        reason = str(envelope.reason or "").strip()
        if reason:
            lines.append(f"决策依据：{reason}")
        next_step = cls._render_next_step(
            envelope.action_args,
            action_name=envelope.action_name,
        )
        if next_step:
            lines.append(f"建议下一步：{next_step}")
        key_facts = cls._render_key_facts(envelope.facts)
        if key_facts:
            lines.append(f"关键依据：{key_facts}")
        lines.append('你现在可以这样干预：回复“状态”查看详情，或回复“人工接管”')
        return "\n".join(lines)

    @classmethod
    def _render_session_directory_notification_text(cls, envelope: NotificationEnvelope) -> str:
        lines = ["Watchdog 多项目目录更新"]
        summary = str(envelope.summary or "").strip()
        if not summary:
            return "\n".join(lines)

        raw_lines = summary.splitlines()
        header = _compact_whitespace(raw_lines[0]) if raw_lines else ""
        if header:
            header = re.sub(r"\s*\|\s*监督=[^|]+", "", header)
            header = re.sub(r"\s*\|\s*最近合议=[^|]+", "", header)
            header = " | ".join(part.strip() for part in header.split("|") if part.strip())
            lines.append(header)

        chunks = [chunk.strip() for chunk in summary.split("\n- ") if chunk.strip()]
        project_chunks = chunks[1:] if chunks and chunks[0].startswith("多项目进展（") else chunks
        for chunk in project_chunks[:6]:
            rendered = cls._render_session_directory_project_line(chunk)
            if rendered:
                lines.append(rendered)

        remaining = len(project_chunks) - min(len(project_chunks), 6)
        if remaining > 0:
            lines.append(f"其余 {remaining} 个项目已省略，回复“项目列表”查看完整目录。")
        return "\n".join(lines)

    @classmethod
    def _render_session_directory_project_line(cls, chunk: str) -> str:
        normalized = str(chunk or "").strip()
        if normalized.startswith("- "):
            normalized = normalized[2:].strip()
        parts = [part.strip() for part in normalized.split(" | ") if part.strip()]
        if len(parts) < 2:
            return ""

        project_id = parts[0]
        phase = parts[1]
        detail = cls._normalize_session_directory_detail(parts[2] if len(parts) > 2 else "")

        fields: dict[str, str] = {}
        for part in parts[3:]:
            key, separator, value = part.partition("=")
            if not separator:
                continue
            key = key.strip()
            value = _truncate_text(value.strip(), limit=36)
            if value and key not in fields:
                fields[key] = value

        segments = [f"- {project_id}：{phase}"]
        if detail:
            segments.append(detail)
        if "关注" in fields:
            segments.append(fields["关注"])
        if "当前目标" in fields:
            segments.append(f"目标={fields['当前目标']}")
        if "下一步" in fields:
            segments.append(f"下一步={fields['下一步']}")
        elif "决策" in fields:
            segments.append(fields["决策"])
        if "上下文" in fields:
            segments.append(f"上下文={fields['上下文']}")
        return "；".join(segment for segment in segments if segment)

    @staticmethod
    def _normalize_session_directory_detail(value: str) -> str:
        normalized = _compact_whitespace(value)
        if not normalized:
            return ""
        normalized = re.sub(
            r"(?:\[steer:[^\]]+\]\s*下一步建议：继续推进\s*)+",
            "",
            normalized,
        )
        normalized = re.sub(r"(?:并优先验证最近改动。?)+", "", normalized)
        normalized = re.sub(r"(?:如果无阻塞，请立即继续执行。?)+", "", normalized)
        normalized = re.sub(r"(?:\d+\.\s*已完成内容\s*)+", "", normalized)
        normalized = re.sub(r"(?:\d+\.\s*当前阻塞点\s*)+", "", normalized)
        normalized = re.sub(r"(?:\d+\.\s*下一步最小动作\s*)+", "", normalized)
        normalized = normalized.strip(" |；。，,")
        return _truncate_text(normalized, limit=48)

    @classmethod
    def _render_notification_text(cls, envelope: NotificationEnvelope) -> str:
        kind_titles = {
            "progress_summary": "Watchdog 任务进展更新",
        }
        lines = [
            kind_titles.get(envelope.notification_kind, "Watchdog 通知"),
            *cls._base_lines(envelope),
        ]
        summary = str(envelope.summary or "").strip()
        if summary:
            lines.append(f"发生了什么：{summary}")
        reason = cls._humanize_reason(envelope.reason)
        if reason:
            lines.append(f"系统参考：{reason}")
        return "\n".join(lines)
