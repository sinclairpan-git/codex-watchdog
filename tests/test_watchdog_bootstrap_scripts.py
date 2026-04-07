from __future__ import annotations

from pathlib import Path


def test_watchdog_launchd_scripts_and_template_are_checked_in() -> None:
    root = Path(__file__).resolve().parents[1]
    start_script = root / "scripts" / "start_watchdog.sh"
    install_script = root / "scripts" / "install_watchdog_launchd.sh"
    plist_template = root / "config" / "examples" / "com.openclaw.watchdog.plist"

    assert start_script.exists()
    start_contents = start_script.read_text(encoding="utf-8")
    assert "uv run uvicorn watchdog.main:create_runtime_app" in start_contents
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
