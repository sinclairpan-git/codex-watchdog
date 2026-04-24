import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from watchdog.secrets import resolve_secret_value
from watchdog.services.memory_hub.contracts import MemoryPreviewContractName


def _normalize_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


class BrainProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    provider: str = Field(default="openai-compatible", min_length=1)
    base_url: str | None = None
    api_key: str | None = None
    api_key_keychain_service: str | None = None
    api_key_keychain_account: str | None = None
    model: str | None = None
    http_timeout_s: float | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WATCHDOG_")

    api_token: str = "dev-token-change-me"
    host: str = "127.0.0.1"
    port: int = 8720
    codex_runtime_base_url: str = "http://127.0.0.1:8710"
    codex_runtime_token: str = "dev-token-change-me"
    http_timeout_s: float = 3.0
    data_dir: str = ".data/watchdog"
    recover_auto_resume: bool = False
    session_spine_refresh_interval_seconds: float = 30.0
    session_spine_freshness_window_seconds: float = 60.0
    resident_orchestrator_interval_seconds: float = 5.0
    resident_expert_stale_after_seconds: float = 900.0
    auto_continue_cooldown_seconds: float = 300.0
    auto_recovery_cooldown_seconds: float = 300.0
    progress_summary_interval_seconds: float = 300.0
    progress_summary_max_age_seconds: float = 600.0
    auto_execute_notification_max_age_seconds: float = 600.0
    local_manual_activity_quiet_window_seconds: float = 600.0
    local_manual_activity_auto_execute_quiet_window_seconds: float = 600.0
    local_manual_activity_recently_idle_window_seconds: float = 1800.0
    default_project_id: str | None = None
    delivery_transport: Literal["feishu", "feishu-app"] = "feishu"
    feishu_base_url: str = "https://open.feishu.cn"
    feishu_event_ingress_mode: Literal["callback", "long_connection"] = "callback"
    feishu_callback_ingress_mode: Literal["callback", "long_connection"] = "callback"
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_receive_id: str | None = None
    feishu_receive_id_type: str = "chat_id"
    feishu_interaction_window_seconds: float = 900.0
    memory_ingest_initial_backoff_seconds: float = 5.0
    memory_ingest_max_attempts: int = 3
    memory_ingest_worker_interval_seconds: float = 5.0
    delivery_worker_interval_seconds: float = 5.0
    delivery_initial_backoff_seconds: float = 5.0
    delivery_max_attempts: int = 3
    delivery_duplicate_suppression_window_seconds: float = 600.0
    memory_preview_ai_autosdlc_cursor_enabled: bool = False
    approval_expiration_seconds: float = 0.0
    ops_blocked_too_long_seconds: float = 900.0
    ops_approval_pending_too_long_seconds: float = 900.0
    ops_delivery_failed_alert_window_seconds: float = 900.0
    ops_provider_degrade_alert_window_seconds: float = 900.0
    release_gate_report_path: str | None = None
    release_gate_risk_policy_version: str = "risk:v1"
    release_gate_decision_input_builder_version: str = "dib:v1"
    release_gate_policy_engine_version: str = "policy:v1"
    release_gate_tool_schema_hash: str = "tool:abc"
    release_gate_memory_provider_adapter_hash: str = "memory:abc"
    release_gate_certification_packet_corpus_ref: str = "tests/fixtures/release_gate_packets.jsonl"
    release_gate_shadow_decision_ledger_ref: str = "tests/fixtures/release_gate_shadow_runs.jsonl"
    brain_provider_name: str = "resident_orchestrator"
    brain_provider_base_url: str | None = None
    brain_provider_api_key: str | None = None
    brain_provider_api_key_keychain_service: str | None = None
    brain_provider_api_key_keychain_account: str | None = None
    brain_provider_model: str | None = None
    brain_provider_http_timeout_s: float = 30.0
    brain_provider_profiles_json: str | None = None

    def model_post_init(self, __context: object) -> None:
        self.brain_provider_api_key = resolve_secret_value(
            explicit_value=self.brain_provider_api_key,
            keychain_service=self.brain_provider_api_key_keychain_service,
            keychain_account=self.brain_provider_api_key_keychain_account,
        )

    def brain_provider_profiles(self) -> dict[str, BrainProviderProfile]:
        raw = _normalize_optional_text(self.brain_provider_profiles_json)
        if raw is None:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("brain_provider_profiles_json must be a JSON object")

        profiles: dict[str, BrainProviderProfile] = {}
        for profile_name, value in payload.items():
            normalized_name = _normalize_optional_text(profile_name)
            if normalized_name is None:
                raise ValueError("brain_provider_profiles_json contains an empty provider name")
            if not isinstance(value, dict):
                raise ValueError("brain_provider_profiles_json entries must be JSON objects")
            profiles[normalized_name] = self._brain_provider_profile_from_payload(
                normalized_name,
                value,
            )
        return profiles

    def active_brain_provider_profile(self) -> BrainProviderProfile | None:
        active_name = _normalize_optional_text(self.brain_provider_name)
        if active_name in (None, "resident_orchestrator"):
            return None

        profiles = self.brain_provider_profiles()
        if active_name in profiles:
            return profiles[active_name]
        if active_name != "openai-compatible":
            return None

        return BrainProviderProfile(
            name="openai-compatible",
            provider="openai-compatible",
            base_url=_normalize_optional_text(self.brain_provider_base_url),
            api_key=_normalize_optional_text(self.brain_provider_api_key),
            api_key_keychain_service=_normalize_optional_text(
                self.brain_provider_api_key_keychain_service
            ),
            api_key_keychain_account=_normalize_optional_text(
                self.brain_provider_api_key_keychain_account
            ),
            model=_normalize_optional_text(self.brain_provider_model),
            http_timeout_s=float(self.brain_provider_http_timeout_s),
        )

    def _brain_provider_profile_from_payload(
        self,
        name: str,
        payload: dict[str, Any],
    ) -> BrainProviderProfile:
        explicit_api_key = _normalize_optional_text(payload.get("api_key"))
        keychain_service = _normalize_optional_text(payload.get("api_key_keychain_service"))
        keychain_account = _normalize_optional_text(payload.get("api_key_keychain_account"))
        api_key = resolve_secret_value(
            explicit_value=explicit_api_key,
            keychain_service=keychain_service,
            keychain_account=keychain_account,
        )
        timeout_value = payload.get("http_timeout_s")
        http_timeout_s = float(timeout_value) if timeout_value is not None else None
        return BrainProviderProfile(
            name=name,
            provider=_normalize_optional_text(payload.get("provider")) or "openai-compatible",
            base_url=_normalize_optional_text(payload.get("base_url")),
            api_key=_normalize_optional_text(api_key),
            api_key_keychain_service=keychain_service,
            api_key_keychain_account=keychain_account,
            model=_normalize_optional_text(payload.get("model")),
            http_timeout_s=http_timeout_s,
        )

    def build_memory_preview_contract_overrides(self) -> dict[MemoryPreviewContractName, bool]:
        return {
            "ai-autosdlc-cursor": bool(self.memory_preview_ai_autosdlc_cursor_enabled),
        }

    def feishu_long_connection_enabled(self) -> bool:
        return (
            self.feishu_event_ingress_mode == "long_connection"
            or self.feishu_callback_ingress_mode == "long_connection"
        )

    def build_runtime_contract(
        self,
        *,
        provider: str,
        model: str,
        prompt_schema_ref: str,
        output_schema_ref: str,
        memory_provider_adapter_hash: str | None = None,
    ) -> dict[str, str]:
        return {
            "provider": provider,
            "model": model,
            "prompt_schema_ref": prompt_schema_ref,
            "output_schema_ref": output_schema_ref,
            "tool_schema_hash": self.release_gate_tool_schema_hash,
            "risk_policy_version": self.release_gate_risk_policy_version,
            "decision_input_builder_version": self.release_gate_decision_input_builder_version,
            "policy_engine_version": self.release_gate_policy_engine_version,
            "memory_provider_adapter_hash": (
                memory_provider_adapter_hash
                or self.release_gate_memory_provider_adapter_hash
            ),
        }
