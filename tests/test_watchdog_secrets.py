from __future__ import annotations

import subprocess

from watchdog.secrets import resolve_secret_value
from watchdog.settings import Settings


def test_resolve_secret_value_prefers_explicit_value() -> None:
    assert (
        resolve_secret_value(
            explicit_value="sk-explicit",
            keychain_service="watchdog.brain-provider",
            keychain_account="default",
        )
        == "sk-explicit"
    )


def test_resolve_secret_value_reads_macos_keychain(monkeypatch) -> None:
    monkeypatch.setattr("watchdog.secrets.sys.platform", "darwin")

    def fake_run(*args, **kwargs):
        assert args[0] == [
            "security",
            "find-generic-password",
            "-w",
            "-s",
            "watchdog.brain-provider",
            "-a",
            "default",
        ]
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="sk-keychain\n")

    monkeypatch.setattr("watchdog.secrets.subprocess.run", fake_run)

    assert (
        resolve_secret_value(
            explicit_value=None,
            keychain_service="watchdog.brain-provider",
            keychain_account="default",
        )
        == "sk-keychain"
    )


def test_settings_resolve_brain_provider_api_key_from_keychain(monkeypatch) -> None:
    monkeypatch.setattr(
        "watchdog.settings.resolve_secret_value",
        lambda **_: "sk-keychain",
    )

    settings = Settings(
        brain_provider_name="openai-compatible",
        brain_provider_base_url="https://provider.example/v1",
        brain_provider_model="minimax-m2.7",
        brain_provider_api_key_keychain_service="watchdog.brain-provider",
        brain_provider_api_key_keychain_account="default",
    )

    assert settings.brain_provider_api_key == "sk-keychain"


def test_settings_resolve_named_brain_provider_profile_from_json_and_keychain(monkeypatch) -> None:
    monkeypatch.setattr(
        "watchdog.settings.resolve_secret_value",
        lambda **kwargs: (
            kwargs["explicit_value"]
            if kwargs["explicit_value"] is not None
            else "sk-profile-keychain"
        ),
    )

    settings = Settings(
        brain_provider_name="deepseek-prod",
        brain_provider_profiles_json=(
            '{"deepseek-prod": {"provider": "openai-compatible", '
            '"base_url": "https://deepseek.example/v1", '
            '"model": "deepseek-chat", '
            '"api_key_keychain_service": "watchdog.brain-provider", '
            '"api_key_keychain_account": "deepseek-prod"}}'
        ),
    )

    profile = settings.active_brain_provider_profile()

    assert profile is not None
    assert profile.name == "deepseek-prod"
    assert profile.provider == "openai-compatible"
    assert profile.base_url == "https://deepseek.example/v1"
    assert profile.model == "deepseek-chat"
    assert profile.api_key == "sk-profile-keychain"
