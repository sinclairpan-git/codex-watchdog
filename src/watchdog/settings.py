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
