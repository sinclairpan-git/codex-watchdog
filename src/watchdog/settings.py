from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WATCHDOG_")

    api_token: str = "dev-token-change-me"
    host: str = "127.0.0.1"
    port: int = 8720
    a_agent_base_url: str = "http://127.0.0.1:8710"
    a_agent_token: str = "dev-token-change-me"
    http_timeout_s: float = 3.0
    data_dir: str = ".data/watchdog"
    recover_auto_resume: bool = False
    session_spine_refresh_interval_seconds: float = 30.0
    session_spine_freshness_window_seconds: float = 60.0
    resident_orchestrator_interval_seconds: float = 5.0
    auto_continue_cooldown_seconds: float = 300.0
    progress_summary_interval_seconds: float = 300.0
    progress_summary_max_age_seconds: float = 600.0
    auto_execute_notification_max_age_seconds: float = 600.0
    local_manual_activity_quiet_window_seconds: float = 600.0
    openclaw_webhook_base_url: str = "http://127.0.0.1:8740"
    openclaw_webhook_token: str = "dev-token-change-me"
    openclaw_webhook_endpoint_state_file: str | None = None
    delivery_worker_interval_seconds: float = 5.0
    delivery_initial_backoff_seconds: float = 5.0
    delivery_max_attempts: int = 3
    approval_expiration_seconds: float = 0.0
    ops_blocked_too_long_seconds: float = 900.0
    ops_approval_pending_too_long_seconds: float = 900.0
    ops_delivery_failed_alert_window_seconds: float = 900.0
    release_gate_report_path: str | None = None
    release_gate_risk_policy_version: str = "risk:v1"
    release_gate_decision_input_builder_version: str = "dib:v1"
    release_gate_policy_engine_version: str = "policy:v1"
    release_gate_tool_schema_hash: str = "tool:abc"
    release_gate_memory_provider_adapter_hash: str = "memory:abc"
