from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="A_AGENT_")

    api_token: str = "dev-token-change-me"
    host: str = "127.0.0.1"
    port: int = 8710
    data_dir: str = ".data/a_control_agent"
    codex_home: str = "~/.codex"
    codex_sync_interval_seconds: float = 30.0
    codex_bridge_enabled: bool = False
    codex_bridge_command: str = "codex app-server --listen stdio://"
    codex_bridge_request_timeout_seconds: float = 10.0
