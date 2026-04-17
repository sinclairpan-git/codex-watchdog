from __future__ import annotations

from a_control_agent.risk.classifier import auto_approve_allowed, classify_risk


def test_l3_patterns() -> None:
    assert classify_risk("git push origin main") == "L3"
    assert classify_risk("rm -rf /tmp") == "L3"


def test_l2_network() -> None:
    assert classify_risk("uv pip install -r requirements.txt") == "L2"


def test_l1_git() -> None:
    assert classify_risk("git checkout -b feat/x") == "L1"
    assert classify_risk("git add .") == "L1"


def test_l0_safe() -> None:
    assert classify_risk("pwd") == "L0"


def test_local_pytest_commands_are_auto_approved() -> None:
    assert auto_approve_allowed(classify_risk("pytest -q")) is True
    assert auto_approve_allowed(classify_risk("uv run pytest -q")) is True
    assert auto_approve_allowed(classify_risk("python3 -m pytest -q")) is True


def test_safe_file_permissions_can_auto_approve_but_network_and_credentials_cannot() -> None:
    assert auto_approve_allowed(classify_risk("permissions:fs.read")) is True
    assert auto_approve_allowed(classify_risk("permissions:fs.read,fs.write")) is True
    assert auto_approve_allowed(classify_risk("permissions:network.http")) is False
    assert auto_approve_allowed(classify_risk("permissions:credentials.read")) is False


def test_auto_approve() -> None:
    assert auto_approve_allowed("L0") is True
    assert auto_approve_allowed("L1") is True
    assert auto_approve_allowed("L2") is False
    assert auto_approve_allowed("L3") is False
