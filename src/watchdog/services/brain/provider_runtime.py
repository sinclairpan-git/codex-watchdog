from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.brain.models import DecisionIntent
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


@dataclass(frozen=True, slots=True)
class OpenAICompatibleBrainProvider:
    settings: Settings
    transport: httpx.BaseTransport | None = None

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

    def decide(
        self,
        *,
        record: Any,
        session_truth: dict[str, object],
        memory_advisory_context: dict[str, object] | None,
    ) -> DecisionIntent:
        profile = self._active_profile()
        if profile is None or not self.configured():
            raise RuntimeError("openai-compatible provider is not configured")

        base_url = str(profile.base_url).rstrip("/")
        url = f"{base_url}/chat/completions"
        body = {
            "model": profile.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return JSON only. "
                        "Keys: session_decision, execution_advice, approval_advice, "
                        "risk_band, goal_coverage, remaining_work_hypothesis, confidence, "
                        "reason_short, evidence_codes."
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
                            "memory_advisory_context": memory_advisory_context,
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
            timeout=(
                profile.http_timeout_s
                if profile.http_timeout_s is not None
                else self.settings.brain_provider_http_timeout_s
            ),
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
        payload = response.json()
        request_id = str(payload.get("id") or "").strip() or None
        content = self._extract_content(payload)
        structured = json.loads(content)
        remaining_work = self._coerce_string_list(structured.get("remaining_work_hypothesis"))
        return DecisionIntent(
            intent=self._map_intent(structured),
            rationale=str(structured.get("reason_short") or "").strip() or None,
            action_arguments=self._build_action_arguments(
                structured,
                remaining_work_hypothesis=remaining_work,
            ),
            confidence=self._coerce_confidence(structured.get("confidence")),
            goal_coverage=str(structured.get("goal_coverage") or "").strip() or None,
            remaining_work_hypothesis=remaining_work,
            evidence_codes=self._coerce_string_list(structured.get("evidence_codes")),
            provider=profile.name,
            model=str(profile.model or "openai-compatible-model"),
            prompt_schema_ref="prompt:brain-decision-v1",
            output_schema_ref="schema:provider-decision-v1",
            provider_request_id=request_id,
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
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider response missing content")
        return OpenAICompatibleBrainProvider._normalize_json_content(content)

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
    def _map_intent(structured: dict[str, object]) -> str:
        session_decision = str(structured.get("session_decision") or "").strip().lower()
        execution_advice = str(structured.get("execution_advice") or "").strip().lower()
        if session_decision in {"complete", "candidate_complete"}:
            return "candidate_closure"
        if session_decision in {"need_recovery", "handoff_to_new_session"}:
            return "propose_recovery"
        if session_decision == "await_human":
            return "require_approval"
        if session_decision == "blocked":
            return "observe_only"
        if execution_advice in {"auto_execute", "notify_then_execute"}:
            return "propose_execute"
        if execution_advice == "notify_only":
            return "suggest_only"
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
        structured: dict[str, object],
        *,
        remaining_work_hypothesis: list[str],
    ) -> dict[str, object]:
        execution_advice = str(structured.get("execution_advice") or "").strip().lower()
        if execution_advice not in {"auto_execute", "notify_then_execute"}:
            return {}
        if remaining_work_hypothesis:
            message = f"下一步建议：{'；'.join(remaining_work_hypothesis)}。"
        else:
            message = str(structured.get("reason_short") or "").strip()
        if not message:
            return {}
        return {
            "message": message,
            "reason_code": "brain_auto_continue",
            "stuck_level": 0,
        }
