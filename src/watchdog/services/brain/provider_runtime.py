from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.brain.models import DecisionIntent
from watchdog.settings import Settings


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

    def configured(self) -> bool:
        return (
            self.settings.brain_provider_name == "openai-compatible"
            and bool(str(self.settings.brain_provider_base_url or "").strip())
            and bool(str(self.settings.brain_provider_api_key or "").strip())
            and bool(str(self.settings.brain_provider_model or "").strip())
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
        if not self.configured():
            raise RuntimeError("openai-compatible provider is not configured")

        base_url = str(self.settings.brain_provider_base_url).rstrip("/")
        url = f"{base_url}/chat/completions"
        body = {
            "model": self.settings.brain_provider_model,
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
            "Authorization": f"Bearer {self.settings.brain_provider_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(
            timeout=self.settings.http_timeout_s,
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
        payload = response.json()
        request_id = str(payload.get("id") or "").strip() or None
        content = self._extract_content(payload)
        structured = json.loads(content)
        return DecisionIntent(
            intent=self._map_intent(structured),
            rationale=str(structured.get("reason_short") or "").strip() or None,
            provider="openai-compatible",
            model=str(self.settings.brain_provider_model or "openai-compatible-model"),
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
        return content

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
