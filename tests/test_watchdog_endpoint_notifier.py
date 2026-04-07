from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from watchdog.endpoint_notifier import EndpointNotifier, EndpointNotifierSettings, extract_latest_trycloudflare_url


class RecordingNotifierClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def notify_watchdog_base_url_changed(
        self,
        *,
        watchdog_base_url: str,
        changed_at: datetime,
        source: str,
    ) -> None:
        self.calls.append((watchdog_base_url, changed_at.isoformat(), source))


def _settings(tmp_path: Path, *, url: str | None = None) -> EndpointNotifierSettings:
    log_path = tmp_path / "watchdog-tunnel.log"
    if url is not None:
        log_path.write_text(f"INF +0000 Your quick Tunnel has been created! {url}\n", encoding="utf-8")
    return EndpointNotifierSettings(
        bootstrap_webhook_base_url="https://bootstrap.example.com",
        bootstrap_webhook_token="secret",
        public_tunnel_log_path=str(log_path),
        public_url_state_file=str(tmp_path / "watchdog-public-url-state.json"),
        public_url_notify_interval_seconds=1.0,
        public_url_source="a-host-watchdog",
        http_timeout_s=3.0,
    )


def test_extract_latest_trycloudflare_url_returns_latest_match() -> None:
    log_text = """
    2026-04-07T18:00:00Z start tunnel
    2026-04-07T18:00:01Z https://first-example.trycloudflare.com
    2026-04-07T18:05:01Z rotated https://second-example.trycloudflare.com
    """.strip()

    assert (
        extract_latest_trycloudflare_url(log_text)
        == "https://second-example.trycloudflare.com"
    )


def test_notifier_posts_new_url_and_persists_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path, url="https://remark-guarantees-sys-seniors.trycloudflare.com")
    client = RecordingNotifierClient()
    notifier = EndpointNotifier(settings=settings, client=client)
    now = datetime(2026, 4, 7, 10, 30, tzinfo=UTC)

    result = notifier.run_once(now=now)

    assert result == "notified"
    assert client.calls == [
        (
            "https://remark-guarantees-sys-seniors.trycloudflare.com",
            now.isoformat(),
            "a-host-watchdog",
        )
    ]
    state_path = Path(settings.public_url_state_file)
    assert state_path.exists()
    assert "remark-guarantees-sys-seniors.trycloudflare.com" in state_path.read_text(encoding="utf-8")


def test_notifier_skips_duplicate_url_without_posting(tmp_path: Path) -> None:
    settings = _settings(tmp_path, url="https://remark-guarantees-sys-seniors.trycloudflare.com")
    client = RecordingNotifierClient()
    notifier = EndpointNotifier(settings=settings, client=client)
    notifier.run_once(now=datetime(2026, 4, 7, 10, 30, tzinfo=UTC))

    second_result = notifier.run_once(now=datetime(2026, 4, 7, 10, 31, tzinfo=UTC))

    assert second_result == "unchanged"
    assert len(client.calls) == 1


def test_notifier_does_not_persist_state_on_delivery_failure(tmp_path: Path) -> None:
    class FailingNotifierClient:
        def notify_watchdog_base_url_changed(
            self,
            *,
            watchdog_base_url: str,
            changed_at: datetime,
            source: str,
        ) -> None:
            raise RuntimeError("network unavailable")

    settings = _settings(tmp_path, url="https://remark-guarantees-sys-seniors.trycloudflare.com")
    notifier = EndpointNotifier(settings=settings, client=FailingNotifierClient())

    try:
        notifier.run_once(now=datetime(2026, 4, 7, 10, 30, tzinfo=UTC))
    except RuntimeError as exc:
        assert str(exc) == "network unavailable"
    else:
        raise AssertionError("expected notifier to surface delivery failure")

    assert not Path(settings.public_url_state_file).exists()
