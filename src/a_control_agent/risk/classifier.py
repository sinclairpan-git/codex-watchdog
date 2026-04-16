"""命令字符串 → L0–L3 启发式分级（PRD §7，可替换为更强策略）。"""

from __future__ import annotations


def classify_risk(command: str) -> str:
    c = command.lower().strip()
    if not c:
        return "L2"
    # L3：高敏感 / 发布 / 破坏性 / 凭证
    l3_markers = (
        "rm -rf",
        "git push",
        "publish",
        "deploy",
        "release",
        "token",
        "secret",
        "credential",
        "credentials.",
        "api_key",
        "openai_api_key",
        "password",
        "绕过",
        "绕过审批",
        "sandbox off",
        "sudo ",
        "chmod 777",
        "/etc/",
        "launchctl",
    )
    if any(m in c for m in l3_markers):
        return "L3"
    # fail-closed：工作区外、网络、发布、系统级与未知边界默认进入人工 gate
    l2_fail_closed_markers = (
        "../",
        "..\\",
        "ssh ",
        "scp ",
        "rsync ",
        "ftp ",
        "telnet ",
        "http://",
        "https://",
        "network.",
        "permissions:network",
    )
    if any(m in c for m in l2_fail_closed_markers):
        return "L2"
    # L2：网络与外部依赖
    l2_markers = (
        "pip install",
        "npm install",
        "pnpm ",
        "yarn ",
        "curl ",
        "wget ",
    )
    if any(m in c for m in l2_markers):
        return "L2"
    # L1：工作区内可逆 git 操作
    if "git checkout -b" in c or c.startswith("git add") or "snapshot" in c:
        return "L1"
    return "L0"


def auto_approve_allowed(risk_level: str) -> bool:
    """L3 绝不允许自动通过（FR-203 / §17.2）。"""
    return risk_level in {"L0", "L1"}
