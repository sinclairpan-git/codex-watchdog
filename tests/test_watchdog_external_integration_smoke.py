from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from watchdog.validation.external_integration_smoke import (
    ExternalIntegrationSmokeConfig,
    exit_code_for_results,
    render_markdown_report,
    render_results,
    run_smoke_checks,
)


def _memory_body(*, active_goal: str = "补齐 release gate") -> dict[str, object]:
    return {
        "request": {
            "project_id": "repo-a",
            "repo_fingerprint": "fingerprint:repo-a",
            "stage": "verification",
            "task_kind": "closeout",
            "capability_request": "release-gate",
            "active_goal": active_goal,
            "current_phase_goal": active_goal,
            "requested_packet_kind": "stage-aware",
        },
        "quality": {
            "key_fact_recall": 0.9,
            "irrelevant_summary_precision": 0.8,
            "token_budget_utilization": 0.4,
            "expansion_miss_rate": 0.1,
        },
    }


def _remote_transport(*, memory_enabled: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        if request.method == "POST" and request.url.path == "/api/v1/watchdog/feishu/events":
            payload = json.loads(request.content.decode("utf-8"))
            if payload.get("type") == "url_verification":
                return httpx.Response(200, json={"challenge": payload["challenge"]})
            assert payload["schema"] == "2.0"
            assert payload["header"]["event_type"] == "im.message.receive_v1"
            content = json.loads(payload["event"]["message"]["content"])
            if content["text"] == "repo:repo-a /goal 继续补齐 Feishu 控制面验收":
                return httpx.Response(
                    200,
                    json={
                        "accepted": True,
                        "event_type": "goal_contract_bootstrap",
                        "data": {
                            "event_type": "goal_contract_bootstrap",
                            "project_id": "repo-a",
                            "session_id": "session:repo-a",
                            "goal_contract_version": "goal-contract:v1",
                        },
                    },
                )
            assert content["text"] == "项目列表"
            return httpx.Response(
                200,
                json={
                    "accepted": True,
                    "event_type": "command_request",
                    "data": {
                        "intent_code": "list_sessions",
                        "reply_code": "session_directory",
                        "message": (
                            "多项目进展（2）\n"
                            "- repo-a | editing_source | editing files | 上下文=low | 恢复=原线程续跑\n"
                            "- repo-b | approval | waiting for approval | 上下文=low | 恢复=新子会话 repo-b:child-v1"
                        ),
                        "sessions": [
                            {"project_id": "repo-a"},
                            {"project_id": "repo-b"},
                        ],
                        "progresses": [
                            {
                                "project_id": "repo-a",
                                "activity_phase": "editing_source",
                                "summary": "editing files",
                                "context_pressure": "low",
                                "recovery_outcome": "same_thread_resume",
                            },
                            {
                                "project_id": "repo-b",
                                "activity_phase": "approval",
                                "summary": "waiting for approval",
                                "context_pressure": "low",
                                "recovery_outcome": "new_child_session",
                                "recovery_child_session_id": "session:repo-b:child-v1",
                            },
                        ],
                    },
                },
            )
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/watchdog/memory/preview/ai-autosdlc-cursor"
        ):
            assert request.headers["Authorization"] == "Bearer wt"
            assert json.loads(request.content.decode("utf-8")) == _memory_body()
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "contract_name": "ai-autosdlc-cursor",
                        "enabled": memory_enabled,
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def _provider_success_transport(
    *,
    base_url: str = "https://provider.example/v1",
    api_key: str = "sk-provider",
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{base_url}/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {api_key}"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-smoke-1",
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


def _provider_failure_transport() -> httpx.MockTransport:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout")

    return httpx.MockTransport(handler)


def _load_smoke_script_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "watchdog_external_integration_smoke.py"
    )
    spec = importlib.util.spec_from_file_location(
        "watchdog_external_integration_smoke_script",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_required_base_env_returns_config_error(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="",
        api_token="",
        data_dir=str(tmp_path),
    )

    results = run_smoke_checks(config=config, targets=("health",))

    assert exit_code_for_results(results) == 2
    assert results[0].check_name == "config"
    assert results[0].status == "failed"
    assert results[0].reason == "missing_required_env"


def test_remote_health_feishu_and_memory_checks_pass(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
        feishu_control_project_id="repo-a",
        feishu_control_goal_message="继续补齐 Feishu 控制面验收",
        memory_preview_ai_autosdlc_cursor_enabled=True,
    )

    results = run_smoke_checks(
        config=config,
        targets=("health", "feishu", "feishu-control", "memory"),
        remote_transport=_remote_transport(memory_enabled=True),
    )

    assert [result.check_name for result in results] == ["health", "feishu", "memory", "feishu-control"]
    assert all(result.status == "passed" for result in results)
    assert exit_code_for_results(results) == 0


def test_feishu_control_check_skips_when_project_binding_not_configured(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
    )

    results = run_smoke_checks(
        config=config,
        targets=("feishu-control",),
        remote_transport=_remote_transport(),
    )

    assert len(results) == 1
    assert results[0].check_name == "feishu-control"
    assert results[0].status == "skipped"
    assert results[0].reason == "operator_confirmation_required"
    assert results[0].evidence["required_action"] == "confirm_mutating_live_target"
    assert results[0].evidence["mutation_path"] == "goal_contract_bootstrap"
    assert exit_code_for_results(results) == 1


def test_feishu_control_check_verifies_goal_bootstrap_contract(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        content = json.loads(payload["event"]["message"]["content"])
        assert content["text"] == "repo:repo-a /goal 继续补齐 Feishu 控制面验收"
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "event_type": "goal_contract_bootstrap",
                "data": {
                    "event_type": "goal_contract_bootstrap",
                    "project_id": "repo-a",
                    "session_id": "session:repo-a",
                    "goal_contract_version": "goal-contract:v1",
                },
            },
        )

    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
        feishu_control_project_id="repo-a",
        feishu_control_goal_message="继续补齐 Feishu 控制面验收",
        feishu_control_expected_session_id="session:repo-a",
    )

    results = run_smoke_checks(
        config=config,
        targets=("feishu-control",),
        remote_transport=httpx.MockTransport(handler),
    )

    assert len(results) == 1
    assert results[0].check_name == "feishu-control"
    assert results[0].status == "passed"
    assert results[0].evidence["goal_contract_version"] == "goal-contract:v1"


def test_feishu_discovery_check_verifies_expected_project_ids(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
        feishu_discovery_expected_project_ids=("repo-a", "repo-b"),
    )

    results = run_smoke_checks(
        config=config,
        targets=("feishu-discovery",),
        remote_transport=_remote_transport(),
    )

    assert len(results) == 1
    assert results[0].check_name == "feishu-discovery"
    assert results[0].status == "passed"
    assert results[0].evidence["command_text"] == "项目列表"
    assert results[0].evidence["project_ids"] == ["repo-a", "repo-b"]
    assert results[0].evidence["progress_project_ids"] == ["repo-a", "repo-b"]
    assert results[0].evidence["message"].startswith("多项目进展（2）")


def test_feishu_discovery_check_uses_documented_default_command_text(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
        feishu_discovery_expected_project_ids=("repo-a", "repo-b"),
        feishu_discovery_command_text="",
    )

    results = run_smoke_checks(
        config=config,
        targets=("feishu-discovery",),
        remote_transport=_remote_transport(),
    )

    assert len(results) == 1
    assert results[0].check_name == "feishu-discovery"
    assert results[0].status == "passed"
    assert results[0].evidence["command_text"] == "项目列表"


def test_feishu_discovery_check_skips_when_expected_projects_not_configured(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
    )

    results = run_smoke_checks(
        config=config,
        targets=("feishu-discovery",),
        remote_transport=_remote_transport(),
    )

    assert len(results) == 1
    assert results[0].check_name == "feishu-discovery"
    assert results[0].status == "skipped"
    assert results[0].reason == "feature_not_configured"


def test_feishu_control_check_uses_dedicated_request_timeout(tmp_path: Path) -> None:
    seen_timeout: dict[str, float] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions["timeout"]
        seen_timeout.update(timeout)
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "event_type": "goal_contract_bootstrap",
                "data": {
                    "event_type": "goal_contract_bootstrap",
                    "project_id": "repo-a",
                    "session_id": "session:repo-a",
                    "goal_contract_version": "goal-contract:v1",
                },
            },
        )

    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        http_timeout_s=20.0,
        feishu_control_http_timeout_s=11.0,
        feishu_verification_token="verify-token",
        feishu_control_project_id="repo-a",
        feishu_control_goal_message="继续补齐 Feishu 控制面验收",
    )

    results = run_smoke_checks(
        config=config,
        targets=("feishu-control",),
        remote_transport=httpx.MockTransport(handler),
    )

    assert results[0].status == "passed"
    assert seen_timeout == {
        "connect": 11.0,
        "read": 11.0,
        "write": 11.0,
        "pool": 11.0,
    }


def test_feishu_check_passes_in_long_connection_mode_without_http_callback(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_event_ingress_mode="long_connection",
        feishu_callback_ingress_mode="long_connection",
        feishu_app_id="cli_long_connection",
        feishu_app_secret="secret-long-connection",
        feishu_verification_token="verify-token",
    )

    results = run_smoke_checks(
        config=config,
        targets=("health", "feishu"),
        remote_transport=httpx.MockTransport(handler),
    )

    assert [result.check_name for result in results] == ["health", "feishu"]
    assert results[1].status == "passed"
    assert results[1].evidence["ingress_mode"] == "long_connection"


def test_all_target_can_be_extended_with_optional_feishu_control(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
        feishu_control_project_id="repo-a",
        feishu_control_goal_message="继续补齐 Feishu 控制面验收",
        feishu_discovery_expected_project_ids=("repo-a", "repo-b"),
    )

    results = run_smoke_checks(
        config=config,
        targets=("all", "feishu-control", "feishu-discovery"),
        remote_transport=_remote_transport(),
    )

    assert [result.check_name for result in results] == [
        "health",
        "feishu",
        "provider",
        "memory",
        "feishu-control",
        "feishu-discovery",
    ]


def test_provider_check_skips_when_external_provider_not_enabled(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
    )

    results = run_smoke_checks(config=config, targets=("provider",))

    assert len(results) == 1
    assert results[0].check_name == "provider"
    assert results[0].status == "skipped"
    assert results[0].reason == "feature_not_enabled"
    assert exit_code_for_results(results) == 1


def test_provider_check_fails_when_openai_mode_is_incomplete(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        brain_provider_name="openai-compatible",
        brain_provider_base_url="https://provider.example/v1",
        brain_provider_api_key="sk-provider",
        brain_provider_model=None,
    )

    results = run_smoke_checks(config=config, targets=("provider",))

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].reason == "missing_required_env"
    assert "brain_provider_model" in results[0].evidence["missing_fields"]
    assert exit_code_for_results(results) == 1


def test_provider_check_proves_provider_and_fallback_paths(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        brain_provider_name="openai-compatible",
        brain_provider_base_url="https://provider.example/v1",
        brain_provider_api_key="sk-provider",
        brain_provider_model="minimax-m2.7",
    )

    results = run_smoke_checks(
        config=config,
        targets=("provider",),
        provider_success_transport=_provider_success_transport(),
        provider_failure_transport=_provider_failure_transport(),
    )

    assert len(results) == 1
    assert results[0].status == "passed"
    assert results[0].evidence["provider_intent"] == "propose_execute"
    assert results[0].evidence["provider_name"] == "openai-compatible"
    assert results[0].evidence["fallback_provider_name"] == "resident_orchestrator"
    assert results[0].evidence["probe_mode"] == "synthetic"


def test_provider_check_supports_named_provider_profiles(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        brain_provider_name="deepseek-prod",
        brain_provider_profiles_json=(
            '{"deepseek-prod": {"provider": "openai-compatible", '
            '"base_url": "https://deepseek.example/v1", '
            '"api_key": "sk-deepseek", '
            '"model": "deepseek-chat"}}'
        ),
    )

    results = run_smoke_checks(
        config=config,
        targets=("provider",),
        provider_success_transport=_provider_success_transport(
            base_url="https://deepseek.example/v1",
            api_key="sk-deepseek",
        ),
        provider_failure_transport=_provider_failure_transport(),
    )

    assert len(results) == 1
    assert results[0].status == "passed"
    assert results[0].evidence["provider_name"] == "deepseek-prod"
    assert results[0].evidence["provider_family"] == "openai-compatible"
    assert results[0].evidence["model"] == "deepseek-chat"


def test_provider_check_can_probe_live_provider_when_enabled(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        brain_provider_name="openai-compatible",
        brain_provider_base_url="https://provider.example/v1",
        brain_provider_api_key="sk-provider",
        brain_provider_model="minimax-m2.7",
        provider_live_mode=True,
        provider_http_timeout_s=27.5,
    )

    results = run_smoke_checks(
        config=config,
        targets=("provider",),
        provider_live_transport=_provider_success_transport(),
        provider_failure_transport=_provider_failure_transport(),
    )

    assert len(results) == 1
    assert results[0].status == "passed"
    assert results[0].evidence["provider_name"] == "openai-compatible"
    assert results[0].evidence["fallback_provider_name"] == "resident_orchestrator"
    assert results[0].evidence["probe_mode"] == "live"


def test_memory_check_fails_when_enabled_flag_does_not_match_response(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        memory_preview_ai_autosdlc_cursor_enabled=True,
    )

    results = run_smoke_checks(
        config=config,
        targets=("memory",),
        remote_transport=_remote_transport(memory_enabled=False),
    )

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].reason == "contract_mismatch"
    assert exit_code_for_results(results) == 1


def test_cli_target_defaults_to_all_only_when_not_explicit() -> None:
    module = _load_smoke_script_module()

    default_exit_code = module.main([])
    targeted_exit_code = module.main(["--target", "provider"])

    assert default_exit_code == 2
    assert targeted_exit_code == 1


def test_render_results_redacts_secret_values(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        brain_provider_name="openai-compatible",
        brain_provider_base_url="https://provider.example/v1",
        brain_provider_api_key="sk-provider",
        brain_provider_model="minimax-m2.7",
    )

    results = run_smoke_checks(
        config=config,
        targets=("provider",),
        provider_success_transport=_provider_success_transport(),
        provider_failure_transport=_provider_failure_transport(),
    )
    rendered = render_results(results)

    assert "sk-provider" not in rendered
    assert '"api_key": "<redacted>"' in rendered


def test_render_markdown_report_redacts_secret_values_and_includes_status(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        brain_provider_name="openai-compatible",
        brain_provider_base_url="https://provider.example/v1",
        brain_provider_api_key="sk-provider",
        brain_provider_model="minimax-m2.7",
    )

    results = run_smoke_checks(
        config=config,
        targets=("provider",),
        provider_success_transport=_provider_success_transport(),
        provider_failure_transport=_provider_failure_transport(),
    )
    rendered = render_markdown_report(
        results=results,
        config=config,
        targets=("provider",),
        generated_at=datetime(2026, 4, 17, 9, 0, tzinfo=UTC),
    )

    assert "# Watchdog External Integration Smoke Report" in rendered
    assert "- Overall Status: `passed`" in rendered
    assert "- Selected Targets: `provider`" in rendered
    assert '"provider_live_mode": false' in rendered
    assert '"feishu_control_http_timeout_s": 15.0' in rendered
    assert '"feishu_discovery_http_timeout_s": 30.0' in rendered
    assert "sk-provider" not in rendered
    assert '"brain_provider_api_key": "<redacted>"' in rendered


def test_render_markdown_report_fails_closed_when_any_selected_target_is_skipped(
    tmp_path: Path,
) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
    )

    results = run_smoke_checks(
        config=config,
        targets=("health", "feishu", "feishu-control"),
        remote_transport=_remote_transport(),
    )
    rendered = render_markdown_report(
        results=results,
        config=config,
        targets=("health", "feishu", "feishu-control"),
        generated_at=datetime(2026, 4, 18, 9, 0, tzinfo=UTC),
    )

    assert "- Overall Status: `failed`" in rendered
    assert "## Check `feishu-control`" in rendered
    assert "- Status: `skipped`" in rendered
    assert "- Reason: `operator_confirmation_required`" in rendered
    assert '"required_action": "confirm_mutating_live_target"' in rendered


def test_cli_can_write_markdown_report_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_script_module()
    report_path = tmp_path / "artifacts" / "watchdog-smoke.md"
    monkeypatch.setenv("WATCHDOG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_NAME", "openai-compatible")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_API_KEY", "sk-provider")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_MODEL", "minimax-m2.7")

    exit_code = module.main(["--target", "provider", "--markdown-report", str(report_path)])

    assert exit_code == 0
    assert report_path.exists()
    contents = report_path.read_text(encoding="utf-8")
    assert "# Watchdog External Integration Smoke Report" in contents
    assert "- Selected Targets: `provider`" in contents


def test_cli_reads_feishu_control_timeout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_script_module()
    captured: dict[str, object] = {}

    def fake_run_smoke_checks(*, config, targets, **_: object):
        captured["config"] = config
        captured["targets"] = targets
        return []

    monkeypatch.setenv("WATCHDOG_BASE_URL", "https://watchdog.example")
    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DATA_DIR", "/tmp/watchdog-smoke")
    monkeypatch.setenv("WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S", "21.5")
    monkeypatch.setattr(module, "run_smoke_checks", fake_run_smoke_checks)

    exit_code = module.main(["--target", "feishu-control"])

    assert exit_code == 0
    assert captured["targets"] == ("feishu-control",)
    assert captured["config"].feishu_control_http_timeout_s == 21.5


def test_cli_reads_feishu_discovery_env(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_script_module()
    captured: dict[str, object] = {}

    def fake_run_smoke_checks(*, config, targets, **_: object):
        captured["config"] = config
        captured["targets"] = targets
        return []

    monkeypatch.setenv("WATCHDOG_BASE_URL", "https://watchdog.example")
    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DATA_DIR", "/tmp/watchdog-smoke")
    monkeypatch.setenv("WATCHDOG_FEISHU_VERIFICATION_TOKEN", "verify-token")
    monkeypatch.setenv("WATCHDOG_SMOKE_FEISHU_DISCOVERY_COMMAND_TEXT", "所有项目进展")
    monkeypatch.setenv(
        "WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS",
        "repo-a, repo-b",
    )
    monkeypatch.setenv("WATCHDOG_SMOKE_FEISHU_DISCOVERY_HTTP_TIMEOUT_S", "19.5")
    monkeypatch.setattr(module, "run_smoke_checks", fake_run_smoke_checks)

    exit_code = module.main(["--target", "feishu-discovery"])

    assert exit_code == 0
    assert captured["targets"] == ("feishu-discovery",)
    assert captured["config"].feishu_discovery_command_text == "所有项目进展"
    assert captured["config"].feishu_discovery_expected_project_ids == ("repo-a", "repo-b")
    assert captured["config"].feishu_discovery_http_timeout_s == 19.5


def test_cli_uses_default_feishu_discovery_timeout_when_env_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_smoke_script_module()
    captured: dict[str, object] = {}

    def fake_run_smoke_checks(*, config, targets, **_: object):
        captured["config"] = config
        captured["targets"] = targets
        return []

    monkeypatch.setenv("WATCHDOG_BASE_URL", "https://watchdog.example")
    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DATA_DIR", "/tmp/watchdog-smoke")
    monkeypatch.setenv("WATCHDOG_FEISHU_VERIFICATION_TOKEN", "verify-token")
    monkeypatch.setenv(
        "WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS",
        "repo-a, repo-b",
    )
    monkeypatch.delenv("WATCHDOG_SMOKE_FEISHU_DISCOVERY_HTTP_TIMEOUT_S", raising=False)
    monkeypatch.setattr(module, "run_smoke_checks", fake_run_smoke_checks)

    exit_code = module.main(["--target", "feishu-discovery"])

    assert exit_code == 0
    assert captured["targets"] == ("feishu-discovery",)
    assert captured["config"].feishu_discovery_http_timeout_s == 30.0


def test_cli_resolves_provider_api_key_from_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_script_module()
    captured: dict[str, object] = {}

    def fake_run_smoke_checks(*, config, targets, **_: object):
        captured["config"] = config
        captured["targets"] = targets
        return []

    monkeypatch.setenv("WATCHDOG_BASE_URL", "https://watchdog.example")
    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DATA_DIR", "/tmp/watchdog-smoke")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_NAME", "openai-compatible")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_MODEL", "minimax-m2.7")
    monkeypatch.setenv(
        "WATCHDOG_BRAIN_PROVIDER_API_KEY_KEYCHAIN_SERVICE",
        "watchdog.brain-provider",
    )
    monkeypatch.setenv(
        "WATCHDOG_BRAIN_PROVIDER_API_KEY_KEYCHAIN_ACCOUNT",
        "default",
    )
    monkeypatch.setattr(module, "run_smoke_checks", fake_run_smoke_checks)
    monkeypatch.setattr(module, "resolve_secret_value", lambda **_: "sk-keychain")

    exit_code = module.main(["--target", "provider"])

    assert exit_code == 0
    assert captured["targets"] == ("provider",)
    assert captured["config"].brain_provider_api_key == "sk-keychain"


def test_cli_reads_provider_live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_script_module()
    captured: dict[str, object] = {}

    def fake_run_smoke_checks(*, config, targets, **_: object):
        captured["config"] = config
        captured["targets"] = targets
        return []

    monkeypatch.setenv("WATCHDOG_BASE_URL", "https://watchdog.example")
    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DATA_DIR", "/tmp/watchdog-smoke")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_NAME", "openai-compatible")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_MODEL", "minimax-m2.7")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_API_KEY", "sk-provider")
    monkeypatch.setenv("WATCHDOG_SMOKE_PROVIDER_LIVE", "true")
    monkeypatch.setenv("WATCHDOG_SMOKE_PROVIDER_HTTP_TIMEOUT_S", "42.0")
    monkeypatch.setattr(module, "run_smoke_checks", fake_run_smoke_checks)

    exit_code = module.main(["--target", "provider"])

    assert exit_code == 0
    assert captured["targets"] == ("provider",)
    assert captured["config"].provider_live_mode is True
    assert captured["config"].provider_http_timeout_s == 42.0


def test_cli_reads_named_provider_profiles_env(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_script_module()
    captured: dict[str, object] = {}

    def fake_run_smoke_checks(*, config, targets, **_: object):
        captured["config"] = config
        captured["targets"] = targets
        return []

    monkeypatch.setenv("WATCHDOG_BASE_URL", "https://watchdog.example")
    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DATA_DIR", "/tmp/watchdog-smoke")
    monkeypatch.setenv("WATCHDOG_BRAIN_PROVIDER_NAME", "deepseek-prod")
    monkeypatch.setenv(
        "WATCHDOG_BRAIN_PROVIDER_PROFILES_JSON",
        (
            '{"deepseek-prod": {"provider": "openai-compatible", '
            '"base_url": "https://deepseek.example/v1", '
            '"api_key": "sk-deepseek", '
            '"model": "deepseek-chat"}}'
        ),
    )
    monkeypatch.setattr(module, "run_smoke_checks", fake_run_smoke_checks)

    exit_code = module.main(["--target", "provider"])

    assert exit_code == 0
    assert captured["targets"] == ("provider",)
    assert captured["config"].brain_provider_name == "deepseek-prod"
    assert captured["config"].brain_provider_profiles_json is not None
