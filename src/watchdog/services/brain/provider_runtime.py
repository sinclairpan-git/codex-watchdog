from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.brain.models import DecisionIntent, ProjectContinuationDecisionInput
from watchdog.services.policy.rules import (
    MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS,
    MANAGED_AGENT_ACTION_BOUNDARY,
)
from watchdog.settings import BrainProviderProfile, Settings


class _ProviderRuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderCapabilityMatrix(_ProviderRuntimeModel):
    strict_json_schema: bool = False
    tool_calling: bool = False
    streaming: bool = False
    max_context: int = 0
    request_id: bool = True
    timeout_profile: str = Field(default="default", min_length=1)
    cost_class: str = Field(default="standard", min_length=1)


class _StructuredProviderDecision(_ProviderRuntimeModel):
    session_decision: str = Field(min_length=1)
    execution_advice: str | None = Field(default=None, min_length=1)
    approval_advice: str | None = Field(default=None, min_length=1)
    risk_band: str | None = Field(default=None, min_length=1)
    goal_coverage: str | None = Field(default=None, min_length=1)
    remaining_work_hypothesis: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason_short: str | None = None
    evidence_codes: list[str] = Field(default_factory=list)


class _StructuredProviderContinuationDecision(_ProviderRuntimeModel):
    continuation_decision: str = Field(min_length=1)
    routing_preference: str | None = Field(default=None, min_length=1)
    goal_coverage: str | None = Field(default=None, min_length=1)
    remaining_work_hypothesis: list[str] = Field(default_factory=list)
    completion_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    next_branch_hypothesis: str | None = None
    decision_reason: str | None = None
    evidence_codes: list[str] = Field(default_factory=list)


PROVIDER_DECISION_OUTPUT_SCHEMA_REF = "schema:provider-decision-v2"
PROVIDER_CONTINUATION_DECISION_OUTPUT_SCHEMA_REF = "schema:provider-continuation-decision-v3"
PROVIDER_OUTPUT_INVALID_DEGRADE_REASON = "provider_output_invalid"
PROVIDER_UNAVAILABLE_DEGRADE_REASON = "provider_unavailable"
PROVIDER_RATE_LIMITED_DEGRADE_REASON = "provider_rate_limited"
_RETRYABLE_PROVIDER_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_PROVIDER_RETRY_ATTEMPTS = 2
_CANONICAL_CONTINUATION_DECISIONS = frozenset(
    {
        "continue_current_branch",
        "recover_current_branch",
        "branch_complete_switch",
        "await_human",
        "project_complete",
        "blocked",
    }
)
_CONTINUATION_DECISION_ALIASES = {
    "continue": "continue_current_branch",
    "continue_branch": "continue_current_branch",
    "proceed": "continue_current_branch",
    "propose_execute": "continue_current_branch",
    "recover": "recover_current_branch",
    "recover_and_proceed": "recover_current_branch",
    "execute_recovery": "recover_current_branch",
    "propose_recovery": "recover_current_branch",
    "route_to_recovery": "recover_current_branch",
    "request_recovery": "recover_current_branch",
    "recover_branch": "recover_current_branch",
    "switch_branch": "branch_complete_switch",
    "branch_switch": "branch_complete_switch",
    "switch_to_next_branch": "branch_complete_switch",
    "move_to_next_branch": "branch_complete_switch",
    "switch_branch_with_recovery_attempt": "branch_complete_switch",
    "request_approval": "await_human",
    "require_approval": "await_human",
    "approval_required": "await_human",
    "await_approval": "await_human",
    "awaiting_approval": "await_human",
    "human_approval": "await_human",
    "request_human_approval": "await_human",
    "complete": "project_complete",
    "candidate_complete": "project_complete",
    "close_session": "project_complete",
}


@dataclass(frozen=True, slots=True)
class _NormalizedProviderDecision:
    continuation_decision: str
    routing_preference: str | None
    goal_coverage: str | None
    remaining_work_hypothesis: list[str]
    completion_confidence: float | None
    next_branch_hypothesis: str | None
    decision_reason: str | None
    evidence_codes: list[str]
    prompt_schema_ref: str
    output_schema_ref: str



class ProviderOutputSchemaError(ValueError):
    def __init__(
        self,
        message: str = "provider response violates schema",
        *,
        schema_ref: str = PROVIDER_DECISION_OUTPUT_SCHEMA_REF,
        degrade_reason: str = PROVIDER_OUTPUT_INVALID_DEGRADE_REASON,
    ) -> None:
        super().__init__(message)
        self.schema_ref = schema_ref
        self.degrade_reason = degrade_reason


@dataclass(frozen=True, slots=True)
class OpenAICompatibleBrainProvider:
    settings: Settings
    transport: httpx.BaseTransport | None = None

    @staticmethod
    def _managed_agent_contract_surface() -> dict[str, object]:
        actions: dict[str, object] = {}
        for action_ref, boundary in MANAGED_AGENT_ACTION_BOUNDARY.items():
            argument_contract = MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS.get(
                action_ref,
                {"allowed_keys": (), "required_keys": ()},
            )
            actions[action_ref] = {
                "capability": boundary["capability"],
                "allowed_brain_intents": list(boundary["allowed_brain_intents"]),
                "auto_execute_allowed_intents": list(boundary["auto_execute_allowed_intents"]),
                "allowed_keys": list(argument_contract["allowed_keys"]),
                "required_keys": list(argument_contract["required_keys"]),
            }
        return {
            "version": "managed-action-contract:v1",
            "actions": actions,
            "provider_output_rules": {
                "derive_requested_action_args_locally": True,
                "forbidden_output_keys": [
                    "action_ref",
                    "action_arguments",
                    "approval_id",
                    "mode",
                    "resume",
                ],
            },
        }

    def _active_profile(self) -> BrainProviderProfile | None:
        profile = self.settings.active_brain_provider_profile()
        if profile is None or profile.provider != "openai-compatible":
            return None
        return profile

    def configured(self) -> bool:
        profile = self._active_profile()
        if profile is None:
            return False
        return (
            bool(str(profile.base_url or "").strip())
            and bool(str(profile.api_key or "").strip())
            and bool(str(profile.model or "").strip())
        )

    def _request_timeout_seconds(self, profile: BrainProviderProfile) -> float:
        provider_timeout = (
            float(profile.http_timeout_s)
            if profile.http_timeout_s is not None
            else float(self.settings.brain_provider_http_timeout_s)
        )
        if provider_timeout > 0.0:
            return provider_timeout
        watchdog_timeout = max(float(self.settings.http_timeout_s or 0.0), 0.0)
        if watchdog_timeout > 0.0:
            return watchdog_timeout
        return 30.0

    def capability_matrix(self) -> ProviderCapabilityMatrix:
        return ProviderCapabilityMatrix(
            strict_json_schema=False,
            tool_calling=False,
            streaming=False,
            max_context=0,
            request_id=True,
            timeout_profile="http-timeout",
            cost_class="external",
        )

    @staticmethod
    def _retryable_status_code(status_code: int) -> bool:
        return status_code in _RETRYABLE_PROVIDER_STATUS_CODES

    @staticmethod
    def _retry_backoff_seconds(attempt_index: int) -> float:
        return 0.25 * float(attempt_index + 1)

    @staticmethod
    def degrade_reason_for_http_status(status_code: int) -> str:
        if status_code == 429:
            return PROVIDER_RATE_LIMITED_DEGRADE_REASON
        return PROVIDER_UNAVAILABLE_DEGRADE_REASON

    @staticmethod
    def _coerce_confidence_like(value: object) -> object:
        normalized = OpenAICompatibleBrainProvider._coerce_scalar_text(value)
        if normalized is None:
            return value
        lowered = normalized.lower()
        confidence_aliases = {
            "low": 0.25,
            "medium": 0.5,
            "med": 0.5,
            "high": 0.85,
        }
        if lowered in confidence_aliases:
            return confidence_aliases[lowered]
        return value

    @staticmethod
    def _coerce_scalar_text(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        if isinstance(value, (int, float, bool)):
            normalized = str(value).strip()
            return normalized or None
        if isinstance(value, dict):
            for key in (
                "code",
                "value",
                "status",
                "label",
                "summary",
                "text",
                "reason",
                "decision",
                "message",
            ):
                if key in value:
                    coerced = OpenAICompatibleBrainProvider._coerce_scalar_text(value.get(key))
                    if coerced:
                        return coerced
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(value).strip() or None
        if isinstance(value, (list, tuple, set)):
            items = [
                item
                for item in (
                    OpenAICompatibleBrainProvider._coerce_scalar_text(part)
                    for part in value
                )
                if item
            ]
            if not items:
                return None
            if len(items) == 1:
                return items[0]
            return " | ".join(items)
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _coerce_string_list_like(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            item = value.strip()
            return [item] if item else []
        if isinstance(value, dict):
            for key in ("items", "steps", "list", "values"):
                if key in value and isinstance(value.get(key), (list, tuple, set)):
                    return OpenAICompatibleBrainProvider._coerce_string_list_like(value.get(key))
            item = OpenAICompatibleBrainProvider._coerce_scalar_text(value)
            return [item] if item else []
        if isinstance(value, (list, tuple, set)):
            items: list[str] = []
            for part in value:
                items.extend(OpenAICompatibleBrainProvider._coerce_string_list_like(part))
            return items
        item = OpenAICompatibleBrainProvider._coerce_scalar_text(value)
        return [item] if item else []

    def decide(
        self,
        *,
        record: Any,
        session_truth: dict[str, object],
        memory_advisory_context: dict[str, object] | None,
        decision_context: ProjectContinuationDecisionInput | dict[str, object] | None = None,
    ) -> DecisionIntent:
        profile = self._active_profile()
        if profile is None or not self.configured():
            raise RuntimeError("openai-compatible provider is not configured")

        base_url = str(profile.base_url).rstrip("/")
        url = f"{base_url}/chat/completions"
        managed_agent_contract = self._managed_agent_contract_surface()
        validated_decision_context = (
            self._validate_decision_context(decision_context)
            if decision_context is not None
            else None
        )
        body = {
            "model": profile.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return JSON only. "
                        "Preferred keys: continuation_decision, routing_preference, goal_coverage, "
                        "remaining_work_hypothesis, completion_confidence, next_branch_hypothesis, "
                        "decision_reason, evidence_codes. "
                        "Use decision_context.project_ref, branch_ref, progress_ref, approval_ref, "
                        "completion_ref, error_ref, and decision_scope_ref to decide whether to "
                        "continue current branch, request human approval, recover, switch branch, "
                        "or mark the current branch/session complete. "
                        "Legacy v2 keys are accepted during migration. "
                        "Do not emit action_ref, action_arguments, approval_id, mode, or resume payloads. "
                        "Watchdog derives requested action arguments locally from the managed action contract."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "project_id": getattr(record, "project_id", ""),
                            "session_id": getattr(record, "thread_id", ""),
                            "summary": getattr(getattr(record, "progress", None), "summary", ""),
                            "facts": [
                                getattr(fact, "fact_code", "")
                                for fact in getattr(record, "facts", [])
                            ],
                            "session_truth": session_truth,
                            "decision_context": (
                                validated_decision_context.model_dump(mode="json")
                                if validated_decision_context is not None
                                else None
                            ),
                            "memory_advisory_context": memory_advisory_context,
                            "managed_agent_contract": managed_agent_contract,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {profile.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(
            timeout=self._request_timeout_seconds(profile),
            transport=self.transport,
            trust_env=False,
        ) as client:
            response: httpx.Response | None = None
            last_error: Exception | None = None
            for attempt in range(_PROVIDER_RETRY_ATTEMPTS):
                try:
                    response = client.post(url, json=body, headers=headers)
                    if (
                        self._retryable_status_code(response.status_code)
                        and attempt + 1 < _PROVIDER_RETRY_ATTEMPTS
                    ):
                        time.sleep(self._retry_backoff_seconds(attempt))
                        continue
                    response.raise_for_status()
                    last_error = None
                    break
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    if (
                        self._retryable_status_code(exc.response.status_code)
                        and attempt + 1 < _PROVIDER_RETRY_ATTEMPTS
                    ):
                        time.sleep(self._retry_backoff_seconds(attempt))
                        continue
                    raise
                except httpx.RequestError as exc:
                    last_error = exc
                    if attempt + 1 < _PROVIDER_RETRY_ATTEMPTS:
                        time.sleep(self._retry_backoff_seconds(attempt))
                        continue
                    raise
            if response is None:
                if last_error is not None:
                    raise last_error
                raise RuntimeError("provider_request_failed")
        payload = response.json()
        request_id = str(payload.get("id") or "").strip() or None
        content = self._extract_content(payload)
        structured = self._validate_provider_decision(content)
        remaining_work = self._coerce_string_list(structured.remaining_work_hypothesis)
        project_id = str(getattr(record, "project_id", "")).strip()
        session_id = str(getattr(record, "thread_id", "")).strip()
        native_thread_id = str(getattr(record, "effective_native_thread_id", "") or "").strip() or "none"
        target_work_item_seq = (
            validated_decision_context.branch_ref.target_work_item_seq
            if validated_decision_context is not None
            else None
        )
        continuation_identity = (
            f"{project_id}:{session_id}:{native_thread_id}:{structured.continuation_decision}"
            if project_id and session_id
            else None
        )
        route_key = (
            f"{continuation_identity}:{validated_decision_context.freshness_ref.snapshot_version}"
            if continuation_identity is not None and validated_decision_context is not None
            else None
        )
        branch_switch_token = (
            f"branch-switch:{project_id}:{target_work_item_seq}:{validated_decision_context.freshness_ref.snapshot_version}"
            if structured.continuation_decision == "branch_complete_switch"
            and project_id
            and target_work_item_seq is not None
            and validated_decision_context is not None
            else None
        )
        return DecisionIntent(
            intent=self._map_intent(structured),
            rationale=str(structured.decision_reason or "").strip() or None,
            action_arguments=self._build_action_arguments(
                structured,
                remaining_work_hypothesis=remaining_work,
            ),
            confidence=self._coerce_confidence(structured.completion_confidence),
            continuation_decision=str(structured.continuation_decision or "").strip() or None,
            routing_preference=str(structured.routing_preference or "").strip() or None,
            completion_confidence=self._coerce_confidence(structured.completion_confidence),
            next_branch_hypothesis=str(structured.next_branch_hypothesis or "").strip() or None,
            continuation_identity=continuation_identity,
            route_key=route_key,
            branch_switch_token=branch_switch_token,
            target_work_item_seq=target_work_item_seq,
            goal_coverage=str(structured.goal_coverage or "").strip() or None,
            remaining_work_hypothesis=remaining_work,
            evidence_codes=self._coerce_string_list(structured.evidence_codes),
            provider=profile.name,
            model=str(profile.model or "openai-compatible-model"),
            prompt_schema_ref=structured.prompt_schema_ref,
            output_schema_ref=structured.output_schema_ref,
            provider_output_schema_ref=structured.output_schema_ref,
            provider_request_id=request_id,
        )

    @staticmethod
    def _normalize_provider_decision_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ProviderOutputSchemaError()
        normalized = dict(payload)
        forbidden_keys = {"action_ref", "action_arguments", "approval_id", "mode", "resume"}
        if forbidden_keys.intersection(normalized):
            raise ProviderOutputSchemaError()
        continuation_allowed_keys = {
            "continuation_decision",
            "routing_preference",
            "goal_coverage",
            "remaining_work_hypothesis",
            "completion_confidence",
            "next_branch_hypothesis",
            "decision_reason",
            "evidence_codes",
        }
        legacy_allowed_keys = {
            "session_decision",
            "execution_advice",
            "approval_advice",
            "risk_band",
            "goal_coverage",
            "remaining_work_hypothesis",
            "confidence",
            "reason_short",
            "evidence_codes",
        }
        if "continuation_decision" in normalized:
            normalized = {
                key: value for key, value in normalized.items() if key in continuation_allowed_keys
            }
        elif "session_decision" in normalized:
            normalized = {key: value for key, value in normalized.items() if key in legacy_allowed_keys}
        goal_coverage = normalized.get("goal_coverage")
        if goal_coverage not in (None, ""):
            normalized["goal_coverage"] = (
                OpenAICompatibleBrainProvider._coerce_scalar_text(goal_coverage) or ""
            )
        for key in (
            "continuation_decision",
            "routing_preference",
            "next_branch_hypothesis",
            "decision_reason",
            "session_decision",
            "execution_advice",
            "approval_advice",
            "risk_band",
            "reason_short",
        ):
            if key in normalized:
                normalized[key] = OpenAICompatibleBrainProvider._coerce_scalar_text(
                    normalized.get(key)
                )
        for key in ("remaining_work_hypothesis", "evidence_codes"):
            normalized[key] = OpenAICompatibleBrainProvider._coerce_string_list_like(
                normalized.get(key)
            )
        for key in ("completion_confidence", "confidence"):
            if key in normalized:
                normalized[key] = OpenAICompatibleBrainProvider._coerce_confidence_like(
                    normalized.get(key)
                )
        continuation_decision = str(normalized.get("continuation_decision") or "").strip().lower()
        routing_preference = str(normalized.get("routing_preference") or "").strip().lower()
        if continuation_decision in _CONTINUATION_DECISION_ALIASES:
            normalized["continuation_decision"] = _CONTINUATION_DECISION_ALIASES[
                continuation_decision
            ]
        elif continuation_decision in {"block", "blocked"} and any(
            token in routing_preference for token in ("recover", "recovery")
        ):
            normalized["continuation_decision"] = "recover_current_branch"
        elif continuation_decision == "block":
            normalized["continuation_decision"] = "blocked"
        elif "continuation_decision" in normalized:
            normalized["continuation_decision"] = continuation_decision
        normalized_continuation_decision = str(
            normalized.get("continuation_decision") or ""
        ).strip()
        if (
            "continuation_decision" in normalized
            and normalized_continuation_decision
            and normalized_continuation_decision not in _CANONICAL_CONTINUATION_DECISIONS
        ):
            raise ProviderOutputSchemaError(
                schema_ref=PROVIDER_CONTINUATION_DECISION_OUTPUT_SCHEMA_REF
            )
        return normalized

    @staticmethod
    def _validate_decision_context(
        value: ProjectContinuationDecisionInput | dict[str, object],
    ) -> ProjectContinuationDecisionInput:
        if isinstance(value, ProjectContinuationDecisionInput):
            return value
        return ProjectContinuationDecisionInput.model_validate(value)

    @staticmethod
    def _validate_provider_decision(content: str) -> _NormalizedProviderDecision:
        try:
            payload = OpenAICompatibleBrainProvider._normalize_provider_decision_payload(
                json.loads(content)
            )
            structured = _StructuredProviderContinuationDecision.model_validate(payload)
            return _NormalizedProviderDecision(
                continuation_decision=str(structured.continuation_decision or "").strip(),
                routing_preference=str(structured.routing_preference or "").strip() or None,
                goal_coverage=str(structured.goal_coverage or "").strip() or None,
                remaining_work_hypothesis=list(structured.remaining_work_hypothesis),
                completion_confidence=structured.completion_confidence,
                next_branch_hypothesis=str(structured.next_branch_hypothesis or "").strip() or None,
                decision_reason=str(structured.decision_reason or "").strip() or None,
                evidence_codes=list(structured.evidence_codes),
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref=PROVIDER_CONTINUATION_DECISION_OUTPUT_SCHEMA_REF,
            )
        except Exception:
            try:
                payload = OpenAICompatibleBrainProvider._normalize_provider_decision_payload(
                    json.loads(content)
                )
                structured = _StructuredProviderDecision.model_validate(payload)
            except Exception as exc:
                raise ProviderOutputSchemaError() from exc
            return _NormalizedProviderDecision(
                continuation_decision=OpenAICompatibleBrainProvider._legacy_continuation_decision(
                    session_decision=structured.session_decision,
                    execution_advice=structured.execution_advice,
                ),
                routing_preference=None,
                goal_coverage=str(structured.goal_coverage or "").strip() or None,
                remaining_work_hypothesis=list(structured.remaining_work_hypothesis),
                completion_confidence=structured.confidence,
                next_branch_hypothesis=None,
                decision_reason=str(structured.reason_short or "").strip() or None,
                evidence_codes=list(structured.evidence_codes),
                prompt_schema_ref="prompt:brain-decision-v2",
                output_schema_ref=PROVIDER_DECISION_OUTPUT_SCHEMA_REF,
            )

    @staticmethod
    def _extract_content(payload: dict[str, object]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("provider response missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError("provider response choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ValueError("provider response missing message")
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return OpenAICompatibleBrainProvider._normalize_json_content(content)
        if isinstance(content, dict):
            candidate = OpenAICompatibleBrainProvider._coerce_scalar_text(content)
            if candidate:
                return OpenAICompatibleBrainProvider._normalize_json_content(candidate)
        if isinstance(content, list):
            parts = [
                part
                for part in (
                    OpenAICompatibleBrainProvider._coerce_scalar_text(item)
                    for item in content
                )
                if part
            ]
            if parts:
                return OpenAICompatibleBrainProvider._normalize_json_content("\n".join(parts))
        raise ValueError("provider response missing content")

    @staticmethod
    def _normalize_json_content(content: str) -> str:
        normalized = content.strip()
        if "</think>" in normalized:
            normalized = normalized.split("</think>", 1)[1].strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            normalized = "\n".join(lines).strip()
        if normalized.startswith("{") and normalized.endswith("}"):
            return normalized
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start != -1 and end != -1 and end > start:
            return normalized[start : end + 1]
        raise ValueError("provider response missing JSON object")

    @staticmethod
    def _legacy_continuation_decision(
        *,
        session_decision: object,
        execution_advice: object,
    ) -> str:
        normalized_session_decision = str(session_decision or "").strip().lower()
        normalized_execution_advice = str(execution_advice or "").strip().lower()
        if normalized_session_decision in {"complete", "candidate_complete"}:
            return "project_complete"
        if normalized_session_decision in {"need_recovery", "handoff_to_new_session"}:
            return "recover_current_branch"
        if normalized_session_decision == "await_human":
            return "await_human"
        if normalized_session_decision == "blocked":
            return "blocked"
        if normalized_execution_advice in {"auto_execute", "notify_then_execute"}:
            return "continue_current_branch"
        return "blocked"

    @staticmethod
    def _map_intent(structured: _NormalizedProviderDecision) -> str:
        continuation_decision = str(structured.continuation_decision or "").strip().lower()
        if continuation_decision == "project_complete":
            return "candidate_closure"
        if continuation_decision in {"recover_current_branch", "execute_recovery"}:
            return "propose_recovery"
        if continuation_decision == "branch_complete_switch":
            return "branch_complete_switch"
        if continuation_decision == "await_human":
            return "require_approval"
        if continuation_decision == "continue_current_branch":
            return "propose_execute"
        return "observe_only"

    @staticmethod
    def _coerce_string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value:
            normalized = str(item or "").strip()
            if normalized:
                items.append(normalized)
        return items

    @staticmethod
    def _coerce_confidence(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        if 0.0 <= normalized <= 1.0:
            return normalized
        return None

    @classmethod
    def _build_action_arguments(
        cls,
        structured: _NormalizedProviderDecision,
        *,
        remaining_work_hypothesis: list[str],
    ) -> dict[str, object]:
        continuation_decision = str(structured.continuation_decision or "").strip().lower()
        if continuation_decision != "continue_current_branch":
            return {}
        if remaining_work_hypothesis:
            message = f"下一步建议：{'；'.join(remaining_work_hypothesis)}。"
        else:
            message = str(structured.decision_reason or "").strip()
        if not message:
            return {}
        return {
            "message": message,
            "reason_code": "brain_auto_continue",
            "stuck_level": 0,
        }
