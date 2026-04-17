from __future__ import annotations

from pathlib import Path


def test_watchdog_launchd_scripts_and_template_are_checked_in() -> None:
    root = Path(__file__).resolve().parents[1]
    start_script = root / "scripts" / "start_watchdog.sh"
    install_script = root / "scripts" / "install_watchdog_launchd.sh"
    plist_template = root / "config" / "examples" / "com.openclaw.watchdog.plist"
    notifier_start_script = root / "scripts" / "start_watchdog_endpoint_notifier.sh"
    notifier_install_script = root / "scripts" / "install_watchdog_endpoint_notifier_launchd.sh"
    notifier_plist_template = (
        root / "config" / "examples" / "com.openclaw.watchdog.endpoint-notifier.plist"
    )

    assert start_script.exists()
    start_contents = start_script.read_text(encoding="utf-8")
    assert 'exec "$UV_BIN" run uvicorn watchdog.main:create_runtime_app' in start_contents
    assert "$HOME/.local/bin" in start_contents
    assert 'command -v uv' in start_contents
    assert "--factory" in start_contents

    install_contents = install_script.read_text(encoding="utf-8")
    assert install_script.exists()
    assert "launchctl bootstrap" in install_contents
    assert "launchctl kickstart -k" in install_contents
    assert "com.openclaw.watchdog" in install_contents

    template_contents = plist_template.read_text(encoding="utf-8")
    assert plist_template.exists()
    assert "<key>RunAtLoad</key>" in template_contents
    assert "<key>KeepAlive</key>" in template_contents
    assert "com.openclaw.watchdog" in template_contents

    assert notifier_start_script.exists()
    notifier_start_contents = notifier_start_script.read_text(encoding="utf-8")
    assert 'exec "$UV_BIN" run python -m watchdog.endpoint_notifier' in notifier_start_contents
    assert "$HOME/.local/bin" in notifier_start_contents
    assert 'command -v uv' in notifier_start_contents

    assert notifier_install_script.exists()
    notifier_install_contents = notifier_install_script.read_text(encoding="utf-8")
    assert "launchctl bootstrap" in notifier_install_contents
    assert "launchctl kickstart -k" in notifier_install_contents
    assert "com.openclaw.watchdog.endpoint-notifier" in notifier_install_contents

    assert notifier_plist_template.exists()
    notifier_template_contents = notifier_plist_template.read_text(encoding="utf-8")
    assert "<key>RunAtLoad</key>" in notifier_template_contents
    assert "<key>KeepAlive</key>" in notifier_template_contents
    assert "com.openclaw.watchdog.endpoint-notifier" in notifier_template_contents


def test_getting_started_watchdog_manual_boot_command_matches_runtime_factory() -> None:
    root = Path(__file__).resolve().parents[1]
    getting_started = root / "docs" / "getting-started.zh-CN.md"
    readme = root / "README.md"

    contents = getting_started.read_text(encoding="utf-8")
    readme_contents = readme.read_text(encoding="utf-8")

    assert "watchdog.main:create_runtime_app" in contents
    assert "--factory" in contents
    assert "watchdog.main:create_runtime_app" in readme_contents
    assert "--factory" in readme_contents
