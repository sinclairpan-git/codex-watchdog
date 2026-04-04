"""命令字符串 → L0–L3 启发式分级（PRD §7，可替换为更强策略）。"""

from __future__ import annotations


def classify_risk(command: str) -> str:
    c = command.lower().strip()
    # L3：高敏感 / 发布 / 破坏性 / 凭证
    l3_markers = (
        "rm -rf",
        "git push",
        "token",
        "secret",
        "绕过",
        "绕过审批",
        "sandbox off",
        "chmod 777",
        "/etc/",
        "launchctl",
    )
    if any(m in c for m in l3_markers):
        return "L3"
    # L2：网络与外部依赖
    l2_markers = (
        "pip install",
        "npm install",
        "pnpm ",
        "yarn ",
        "curl ",
        "wget ",
        "https://",
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
