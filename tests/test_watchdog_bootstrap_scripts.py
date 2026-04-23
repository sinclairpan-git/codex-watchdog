from __future__ import annotations

from pathlib import Path


def test_watchdog_launchd_scripts_and_template_are_checked_in() -> None:
    root = Path(__file__).resolve().parents[1]
    start_script = root / "scripts" / "start_watchdog.sh"
    install_script = root / "scripts" / "install_watchdog_launchd.sh"
    plist_template = root / "config" / "examples" / "com.codex.watchdog.plist"

    assert start_script.exists()
    start_contents = start_script.read_text(encoding="utf-8")
    assert 'exec "$UV_BIN" run python -m uvicorn watchdog.main:create_runtime_app' in start_contents
    assert "$HOME/.local/bin" in start_contents
    assert 'command -v uv' in start_contents
    assert "--factory" in start_contents

    install_contents = install_script.read_text(encoding="utf-8")
    assert install_script.exists()
    assert "launchctl bootstrap" in install_contents
    assert "launchctl kickstart -k" in install_contents
    assert "com.codex.watchdog" in install_contents

    template_contents = plist_template.read_text(encoding="utf-8")
    assert plist_template.exists()
    assert "<key>RunAtLoad</key>" in template_contents
    assert "<key>KeepAlive</key>" in template_contents
    assert "com.codex.watchdog" in template_contents


def test_getting_started_watchdog_manual_boot_command_matches_runtime_factory() -> None:
    root = Path(__file__).resolve().parents[1]
    getting_started = root / "docs" / "getting-started.zh-CN.md"
    readme = root / "README.md"
    smoke_script = root / "scripts" / "watchdog_external_integration_smoke.py"

    contents = getting_started.read_text(encoding="utf-8")
    readme_contents = readme.read_text(encoding="utf-8")

    assert smoke_script.exists()
    assert "scripts/watchdog_external_integration_smoke.py" in contents
    assert "uv run python scripts/watchdog_external_integration_smoke.py" in contents
    assert "scripts/watchdog_external_integration_smoke.py" in readme_contents
    assert "uv run python scripts/watchdog_external_integration_smoke.py" in readme_contents
    assert "watchdog.main:create_runtime_app" in contents
    assert "--factory" in contents
    assert "watchdog.main:create_runtime_app" in readme_contents
    assert "--factory" in readme_contents
