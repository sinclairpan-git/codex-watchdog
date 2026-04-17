from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx

from watchdog.validation.external_integration_smoke import (
    ExternalIntegrationSmokeConfig,
    exit_code_for_results,
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


def _provider_success_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer sk-provider"
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
    assert results[0].reason == "feature_not_configured"


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


def test_all_target_can_be_extended_with_optional_feishu_control(tmp_path: Path) -> None:
    config = ExternalIntegrationSmokeConfig(
        base_url="https://watchdog.example",
        api_token="wt",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
        feishu_control_project_id="repo-a",
        feishu_control_goal_message="继续补齐 Feishu 控制面验收",
    )

    results = run_smoke_checks(
        config=config,
        targets=("all", "feishu-control"),
        remote_transport=_remote_transport(),
    )

    assert [result.check_name for result in results] == [
        "health",
        "feishu",
        "provider",
        "memory",
        "feishu-control",
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
    assert exit_code_for_results(results) == 0


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
    assert targeted_exit_code == 0


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
