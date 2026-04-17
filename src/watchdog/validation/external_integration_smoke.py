from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence
from uuid import uuid4

import httpx

from watchdog.contracts.session_spine.models import SessionProjection, TaskProgressView
from watchdog.services.brain.service import BrainDecisionService
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.session_spine.store import PersistedSessionRecord
from watchdog.settings import Settings

SmokeStatus = Literal["passed", "failed", "skipped"]

DEFAULT_TARGETS = ("health", "feishu", "provider", "memory")
OPTIONAL_TARGETS = ("feishu-control",)
SUPPORTED_TARGETS = DEFAULT_TARGETS + OPTIONAL_TARGETS
REMOTE_TARGETS = frozenset({"health", "feishu", "feishu-control", "memory"})


@dataclass(frozen=True)
class ExternalIntegrationSmokeConfig:
    base_url: str
    api_token: str
    data_dir: str
    http_timeout_s: float = 3.0
    feishu_control_http_timeout_s: float = 15.0
    feishu_event_ingress_mode: str = "callback"
    feishu_callback_ingress_mode: str = "callback"
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_control_project_id: str | None = None
    feishu_control_goal_message: str | None = None
    feishu_control_expected_session_id: str | None = None
    feishu_control_actor_open_id: str = "ou_watchdog_smoke"
    brain_provider_name: str = "resident_orchestrator"
    brain_provider_base_url: str | None = None
    brain_provider_api_key: str | None = None
    brain_provider_model: str | None = None
    memory_preview_ai_autosdlc_cursor_enabled: bool = False


@dataclass(frozen=True)
class SmokeCheckResult:
    check_name: str
    status: SmokeStatus
    reason: str
    evidence: dict[str, Any]


def run_smoke_checks(
    *,
    config: ExternalIntegrationSmokeConfig,
    targets: Sequence[str],
    remote_transport: httpx.BaseTransport | None = None,
    provider_success_transport: httpx.BaseTransport | None = None,
    provider_failure_transport: httpx.BaseTransport | None = None,
) -> list[SmokeCheckResult]:
    normalized_targets = _normalize_targets(targets)
    if normalized_targets & REMOTE_TARGETS:
        missing_base_fields = [
            field_name
            for field_name, value in (
                ("base_url", config.base_url),
                ("api_token", config.api_token),
            )
            if not str(value or "").strip()
        ]
        if missing_base_fields:
            return [
                SmokeCheckResult(
                    check_name="config",
                    status="failed",
                    reason="missing_required_env",
                    evidence={"missing_fields": missing_base_fields},
                )
            ]

    results: list[SmokeCheckResult] = []
    remote_client: httpx.Client | None = None
    health_ok = True
    if normalized_targets & REMOTE_TARGETS:
        remote_client = httpx.Client(
            base_url=str(config.base_url).rstrip("/"),
            timeout=config.http_timeout_s,
            transport=remote_transport,
            trust_env=False,
        )

    try:
        for target in SUPPORTED_TARGETS:
            if target not in normalized_targets:
                continue
            if target == "health":
                result = _run_health_check(config=config, client=remote_client)
                health_ok = result.status == "passed"
            elif target == "feishu":
                result = _run_feishu_check(
                    config=config,
                    client=remote_client,
                    health_ok=health_ok,
                )
            elif target == "feishu-control":
                result = _run_feishu_control_check(
                    config=config,
                    client=remote_client,
                    health_ok=health_ok,
                )
            elif target == "provider":
                result = _run_provider_check(
                    config=config,
                    success_transport=provider_success_transport,
                    failure_transport=provider_failure_transport,
                )
            else:
                result = _run_memory_check(
                    config=config,
                    client=remote_client,
                    health_ok=health_ok,
                )
            results.append(result)
    finally:
        if remote_client is not None:
            remote_client.close()

    return results


def render_results(results: Sequence[SmokeCheckResult]) -> str:
    payload = [_redact_payload(asdict(result)) for result in results]
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def render_markdown_report(
    *,
    results: Sequence[SmokeCheckResult],
    config: ExternalIntegrationSmokeConfig,
    targets: Sequence[str],
    generated_at: datetime | None = None,
) -> str:
    normalized_targets = tuple(
        target for target in SUPPORTED_TARGETS if target in _normalize_targets(targets)
    )
    overall_status = _overall_status(results)
    timestamp = (generated_at or datetime.now(tz=UTC)).astimezone(UTC).isoformat()
    config_snapshot = _redact_payload(
        {
            "base_url": config.base_url,
            "http_timeout_s": config.http_timeout_s,
            "feishu_control_http_timeout_s": config.feishu_control_http_timeout_s,
            "feishu_event_ingress_mode": config.feishu_event_ingress_mode,
            "feishu_callback_ingress_mode": config.feishu_callback_ingress_mode,
            "feishu_app_id": config.feishu_app_id,
            "feishu_app_secret": config.feishu_app_secret,
            "brain_provider_name": config.brain_provider_name,
            "brain_provider_base_url": config.brain_provider_base_url,
            "brain_provider_api_key": config.brain_provider_api_key,
            "brain_provider_model": config.brain_provider_model,
            "memory_preview_ai_autosdlc_cursor_enabled": config.memory_preview_ai_autosdlc_cursor_enabled,
            "feishu_verification_token": config.feishu_verification_token,
            "feishu_control_project_id": config.feishu_control_project_id,
            "feishu_control_expected_session_id": config.feishu_control_expected_session_id,
        }
    )
    lines = [
        "# Watchdog External Integration Smoke Report",
        "",
        "- Scope: repo-local live acceptance evidence only; external org install, domain wiring, and secret issuance remain outside repository truth.",
        f"- Generated At (UTC): `{timestamp}`",
        f"- Selected Targets: `{', '.join(normalized_targets)}`",
        f"- Overall Status: `{overall_status}`",
        "",
        "## Runtime Snapshot",
        "",
        "```json",
        json.dumps(config_snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]

    for result in results:
        lines.extend(
            [
                "",
                f"## Check `{result.check_name}`",
                "",
                f"- Status: `{result.status}`",
                f"- Reason: `{result.reason}`",
                "- Evidence:",
                "",
                "```json",
                json.dumps(_redact_payload(result.evidence), ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def exit_code_for_results(results: Sequence[SmokeCheckResult]) -> int:
    if any(result.check_name == "config" and result.status == "failed" for result in results):
        return 2
    if any(result.status == "failed" for result in results):
        return 1
    return 0


def _normalize_targets(targets: Sequence[str]) -> set[str]:
    normalized = {str(target).strip().lower() for target in targets if str(target).strip()}
    if not normalized or "all" in normalized:
        return set(DEFAULT_TARGETS).union(normalized.intersection(OPTIONAL_TARGETS))
    unknown = normalized.difference(SUPPORTED_TARGETS)
    if unknown:
        raise ValueError(f"unsupported targets: {', '.join(sorted(unknown))}")
    return normalized


def _run_health_check(
    *,
    config: ExternalIntegrationSmokeConfig,
    client: httpx.Client | None,
) -> SmokeCheckResult:
    assert client is not None
    try:
        response = client.get("/healthz")
    except httpx.HTTPError as exc:
        return SmokeCheckResult(
            check_name="health",
            status="failed",
            reason="service_unreachable",
            evidence={"url": f"{config.base_url.rstrip('/')}/healthz", "error": str(exc)},
        )
    if response.status_code != 200:
        return SmokeCheckResult(
            check_name="health",
            status="failed",
            reason="unexpected_http_status",
            evidence={"status_code": response.status_code},
        )
    return SmokeCheckResult(
        check_name="health",
        status="passed",
        reason="ok",
        evidence={"url": f"{config.base_url.rstrip('/')}/healthz"},
    )


def _run_feishu_check(
    *,
    config: ExternalIntegrationSmokeConfig,
    client: httpx.Client | None,
    health_ok: bool,
) -> SmokeCheckResult:
    if not health_ok:
        return SmokeCheckResult(
            check_name="feishu",
            status="failed",
            reason="service_unreachable",
            evidence={"blocked_by": "health"},
        )
    if _feishu_uses_long_connection(config):
        missing_fields = [
            field_name
            for field_name, value in (
                ("feishu_app_id", config.feishu_app_id),
                ("feishu_app_secret", config.feishu_app_secret),
                ("feishu_verification_token", config.feishu_verification_token),
            )
            if not str(value or "").strip()
        ]
        if missing_fields:
            return SmokeCheckResult(
                check_name="feishu",
                status="failed",
                reason="missing_required_env",
                evidence={"missing_fields": missing_fields},
            )
        sdk_available = importlib.util.find_spec("lark_oapi") is not None
        if not sdk_available:
            return SmokeCheckResult(
                check_name="feishu",
                status="failed",
                reason="sdk_not_installed",
                evidence={"required_package": "lark-oapi"},
            )
        return SmokeCheckResult(
            check_name="feishu",
            status="passed",
            reason="ok",
            evidence={
                "ingress_mode": "long_connection",
                "callback_mode": config.feishu_callback_ingress_mode,
                "required_package": "lark-oapi",
            },
        )
    if not str(config.feishu_verification_token or "").strip():
        return SmokeCheckResult(
            check_name="feishu",
            status="failed",
            reason="missing_required_env",
            evidence={"missing_fields": ["feishu_verification_token"]},
        )
    assert client is not None
    body = {
        "type": "url_verification",
        "token": config.feishu_verification_token,
        "challenge": "watchdog-smoke-challenge",
    }
    try:
        response = client.post("/api/v1/watchdog/feishu/events", json=body)
    except httpx.HTTPError as exc:
        return SmokeCheckResult(
            check_name="feishu",
            status="failed",
            reason="service_unreachable",
            evidence={"error": str(exc)},
        )
    if response.status_code != 200:
        return SmokeCheckResult(
            check_name="feishu",
            status="failed",
            reason="unexpected_http_status",
            evidence={"status_code": response.status_code},
        )
    payload = response.json()
    if payload.get("challenge") != body["challenge"]:
        return SmokeCheckResult(
            check_name="feishu",
            status="failed",
            reason="contract_mismatch",
            evidence={"response": payload},
        )
    return SmokeCheckResult(
        check_name="feishu",
        status="passed",
        reason="ok",
        evidence={"challenge": body["challenge"]},
    )


def _run_feishu_control_check(
    *,
    config: ExternalIntegrationSmokeConfig,
    client: httpx.Client | None,
    health_ok: bool,
) -> SmokeCheckResult:
    if not health_ok:
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="service_unreachable",
            evidence={"blocked_by": "health"},
        )
    if not str(config.feishu_verification_token or "").strip():
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="missing_required_env",
            evidence={"missing_fields": ["feishu_verification_token"]},
        )
    missing_fields = [
        field_name
        for field_name, value in (
            ("feishu_control_project_id", config.feishu_control_project_id),
            ("feishu_control_goal_message", config.feishu_control_goal_message),
        )
        if not str(value or "").strip()
    ]
    if missing_fields:
        return SmokeCheckResult(
            check_name="feishu-control",
            status="skipped",
            reason="feature_not_configured",
            evidence={"missing_fields": missing_fields},
        )
    assert client is not None
    body = _feishu_control_body(config)
    request_timeout_s = float(config.feishu_control_http_timeout_s)
    try:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=body,
            timeout=request_timeout_s,
        )
    except httpx.HTTPError as exc:
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="service_unreachable",
            evidence={"error": str(exc)},
        )
    if response.status_code != 200:
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="unexpected_http_status",
            evidence={"status_code": response.status_code},
        )
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if payload.get("accepted") is not True or payload.get("event_type") != "goal_contract_bootstrap":
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="contract_mismatch",
            evidence={"response": payload},
        )
    if not isinstance(data, Mapping):
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="contract_mismatch",
            evidence={"response": payload},
        )
    if data.get("project_id") != config.feishu_control_project_id:
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="contract_mismatch",
            evidence={
                "expected_project_id": config.feishu_control_project_id,
                "response": payload,
            },
        )
    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="contract_mismatch",
            evidence={"response": payload},
        )
    if (
        str(config.feishu_control_expected_session_id or "").strip()
        and session_id != config.feishu_control_expected_session_id
    ):
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="contract_mismatch",
            evidence={
                "expected_session_id": config.feishu_control_expected_session_id,
                "actual_session_id": session_id,
            },
        )
    goal_contract_version = str(data.get("goal_contract_version") or "").strip()
    if not goal_contract_version:
        return SmokeCheckResult(
            check_name="feishu-control",
            status="failed",
            reason="contract_mismatch",
            evidence={"response": payload},
        )
    return SmokeCheckResult(
        check_name="feishu-control",
        status="passed",
        reason="ok",
        evidence={
            "project_id": data.get("project_id"),
            "session_id": session_id,
            "goal_contract_version": goal_contract_version,
            "replayed": bool(data.get("replayed")),
        },
    )


def _run_provider_check(
    *,
    config: ExternalIntegrationSmokeConfig,
    success_transport: httpx.BaseTransport | None,
    failure_transport: httpx.BaseTransport | None,
) -> SmokeCheckResult:
    if config.brain_provider_name != "openai-compatible":
        return SmokeCheckResult(
            check_name="provider",
            status="skipped",
            reason="feature_not_enabled",
            evidence={"provider_name": config.brain_provider_name},
        )

    missing_fields = [
        field_name
        for field_name, value in (
            ("brain_provider_base_url", config.brain_provider_base_url),
            ("brain_provider_api_key", config.brain_provider_api_key),
            ("brain_provider_model", config.brain_provider_model),
        )
        if not str(value or "").strip()
    ]
    if missing_fields:
        return SmokeCheckResult(
            check_name="provider",
            status="failed",
            reason="missing_required_env",
            evidence={"missing_fields": missing_fields},
        )

    success_intent = _probe_provider_intent(
        config=config,
        transport=success_transport or _default_provider_success_transport(),
    )
    failure_intent = _probe_provider_intent(
        config=config,
        transport=failure_transport or _default_provider_failure_transport(),
    )
    if success_intent.provider != "openai-compatible":
        return SmokeCheckResult(
            check_name="provider",
            status="failed",
            reason="contract_mismatch",
            evidence={"expected_provider": "openai-compatible", "actual_provider": success_intent.provider},
        )
    if failure_intent.provider != "resident_orchestrator":
        return SmokeCheckResult(
            check_name="provider",
            status="failed",
            reason="contract_mismatch",
            evidence={
                "expected_fallback_provider": "resident_orchestrator",
                "actual_fallback_provider": failure_intent.provider,
            },
        )
    return SmokeCheckResult(
        check_name="provider",
        status="passed",
        reason="ok",
        evidence={
            "provider_name": success_intent.provider,
            "provider_intent": success_intent.intent,
            "fallback_provider_name": failure_intent.provider,
            "model": config.brain_provider_model,
            "base_url": config.brain_provider_base_url,
            "api_key": config.brain_provider_api_key,
        },
    )


def _run_memory_check(
    *,
    config: ExternalIntegrationSmokeConfig,
    client: httpx.Client | None,
    health_ok: bool,
) -> SmokeCheckResult:
    if not health_ok:
        return SmokeCheckResult(
            check_name="memory",
            status="failed",
            reason="service_unreachable",
            evidence={"blocked_by": "health"},
        )
    assert client is not None
    try:
        response = client.post(
            "/api/v1/watchdog/memory/preview/ai-autosdlc-cursor",
            json=_memory_preview_body(),
            headers={"Authorization": f"Bearer {config.api_token}"},
        )
    except httpx.HTTPError as exc:
        return SmokeCheckResult(
            check_name="memory",
            status="failed",
            reason="service_unreachable",
            evidence={"error": str(exc)},
        )
    if response.status_code != 200:
        return SmokeCheckResult(
            check_name="memory",
            status="failed",
            reason="unexpected_http_status",
            evidence={"status_code": response.status_code},
        )
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if payload.get("success") is not True or not isinstance(data, Mapping):
        return SmokeCheckResult(
            check_name="memory",
            status="failed",
            reason="contract_mismatch",
            evidence={"response": payload},
        )
    if data.get("contract_name") != "ai-autosdlc-cursor":
        return SmokeCheckResult(
            check_name="memory",
            status="failed",
            reason="contract_mismatch",
            evidence={"response": payload},
        )
    if bool(data.get("enabled")) is not bool(config.memory_preview_ai_autosdlc_cursor_enabled):
        return SmokeCheckResult(
            check_name="memory",
            status="failed",
            reason="contract_mismatch",
            evidence={
                "expected_enabled": bool(config.memory_preview_ai_autosdlc_cursor_enabled),
                "actual_enabled": bool(data.get("enabled")),
            },
        )
    return SmokeCheckResult(
        check_name="memory",
        status="passed",
        reason="ok",
        evidence={
            "contract_name": "ai-autosdlc-cursor",
            "enabled": bool(data.get("enabled")),
        },
    )


def _probe_provider_intent(
    *,
    config: ExternalIntegrationSmokeConfig,
    transport: httpx.BaseTransport,
):
    data_dir = Path(config.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(data_dir),
            brain_provider_name=config.brain_provider_name,
            brain_provider_base_url=config.brain_provider_base_url,
            brain_provider_api_key=config.brain_provider_api_key,
            brain_provider_model=config.brain_provider_model,
            http_timeout_s=config.http_timeout_s,
        ),
        session_service=SessionService(SessionServiceStore(data_dir / "session_service_smoke.json")),
        provider_transport=transport,
    )
    return service.evaluate_session(record=_synthetic_record())


def _synthetic_record() -> PersistedSessionRecord:
    return PersistedSessionRecord(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_seq=1,
        fact_snapshot_version="fact-v1",
        last_refreshed_at="2026-04-16T00:00:00Z",
        session=SessionProjection(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            session_state="active",
            activity_phase="editing_source",
            attention_state="normal",
            headline="editing files",
            pending_approval_count=0,
            available_intents=["continue"],
        ),
        progress=TaskProgressView(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            activity_phase="editing_source",
            summary="ship feishu and memory hub integration",
            files_touched=["src/example.py"],
            context_pressure="low",
            stuck_level=0,
            primary_fact_codes=[],
            blocker_fact_codes=[],
            last_progress_at="2026-04-16T00:00:00Z",
        ),
        facts=[],
        approval_queue=[],
    )


def _memory_preview_body() -> dict[str, object]:
    return {
        "request": {
            "project_id": "repo-a",
            "repo_fingerprint": "fingerprint:repo-a",
            "stage": "verification",
            "task_kind": "closeout",
            "capability_request": "release-gate",
            "active_goal": "补齐 release gate",
            "current_phase_goal": "补齐 release gate",
            "requested_packet_kind": "stage-aware",
        },
        "quality": {
            "key_fact_recall": 0.9,
            "irrelevant_summary_precision": 0.8,
            "token_budget_utilization": 0.4,
            "expansion_miss_rate": 0.1,
        },
    }


def _feishu_control_body(config: ExternalIntegrationSmokeConfig) -> dict[str, object]:
    event_id = f"evt-feishu-smoke-{uuid4().hex}"
    message_id = f"om_feishu_smoke_{uuid4().hex}"
    create_time = str(int(datetime.now(tz=UTC).timestamp() * 1000))
    text = f"repo:{str(config.feishu_control_project_id).strip()} /goal {str(config.feishu_control_goal_message).strip()}"
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": create_time,
            "token": config.feishu_verification_token,
            "app_id": "cli_watchdog_smoke",
            "tenant_key": "watchdog-smoke",
        },
        "event": {
            "message": {
                "message_id": message_id,
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            "sender": {
                "sender_id": {"open_id": config.feishu_control_actor_open_id},
            },
        },
    }


def _default_provider_success_transport() -> httpx.BaseTransport:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-smoke-default",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "session_decision": "active",
                                    "execution_advice": "auto_execute",
                                    "approval_advice": "none",
                                    "risk_band": "low",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "confidence": 0.91,
                                    "reason_short": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


def _default_provider_failure_transport() -> httpx.BaseTransport:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout")

    return httpx.MockTransport(handler)


def _overall_status(results: Sequence[SmokeCheckResult]) -> SmokeStatus:
    if any(result.status == "failed" for result in results):
        return "failed"
    if results and all(result.status == "skipped" for result in results):
        return "skipped"
    return "passed"


def _feishu_uses_long_connection(config: ExternalIntegrationSmokeConfig) -> bool:
    return (
        str(config.feishu_event_ingress_mode).strip().lower() == "long_connection"
        or str(config.feishu_callback_ingress_mode).strip().lower() == "long_connection"
    )


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            normalized_key = key.lower()
            if (
                normalized_key in {"api_key", "token", "authorization", "secret"}
                or normalized_key.endswith("_api_key")
                or normalized_key.endswith("_token")
                or normalized_key.endswith("_secret")
            ) and nested not in (None, ""):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_payload(nested)
        return redacted
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value
