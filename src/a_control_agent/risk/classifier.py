"""命令字符串 → L0–L3 启发式分级（PRD §7，可替换为更强策略）。"""

from __future__ import annotations

import re


def _contains_command_word(command: str, marker: str) -> bool:
    return (
        re.search(
            rf"(^|[\s\"';|&()])(?:[^\s\"';|&()]+/)*{re.escape(marker)}\b",
            command,
        )
        is not None
    )


def classify_risk(command: str) -> str:
    c = command.lower().strip()
    if not c:
        return "L2"
    parts = c.split()
    first_token = parts[0] if parts else ""
    executable = first_token.rsplit("/", 1)[-1]
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
    sensitive_path_markers = (
        "~/.ssh",
        "/.ssh/",
        ".aws/credentials",
        ".kube/config",
        "/proc/self/environ",
        "/proc/self/cmdline",
        "id_rsa",
        "id_ed25519",
        ".pypirc",
        ".npmrc",
    )
    if any(m in c for m in l3_markers):
        return "L3"
    if any(m in c for m in sensitive_path_markers):
        return "L3"
    fail_closed_network_commands = (
        "ssh",
        "ssh-keyscan",
        "scp",
        "rsync",
        "ftp",
        "telnet",
        "ping",
        "dig",
        "nslookup",
        "nc",
        "netcat",
    )
    fail_closed_system_commands = (
        "systemctl",
        "service",
        "rc-service",
        "systemd-run",
        "shutdown",
        "reboot",
        "poweroff",
        "halt",
    )
    if executable in fail_closed_network_commands or executable in fail_closed_system_commands:
        return "L2"
    if any(_contains_command_word(c, marker) for marker in fail_closed_network_commands):
        return "L2"
    if any(_contains_command_word(c, marker) for marker in fail_closed_system_commands):
        return "L2"
    if executable == "init" and any(arg in {"0", "6"} for arg in parts[1:]):
        return "L2"
    if _contains_command_word(c, "init 0") or _contains_command_word(c, "init 6"):
        return "L2"
    # fail-closed：工作区外、网络、发布、系统级与未知边界默认进入人工 gate
    l2_fail_closed_markers = (
        "../",
        "..\\",
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
    if (
        "&&" in c
        or "||" in c
        or ";" in c
        or "|" in c
        or "&" in c
        or "\n" in c
        or "\r" in c
        or "\t" in c
        or "\v" in c
        or "\f" in c
        or "$(" in c
        or "<(" in c
        or ">(" in c
        or "`" in c
    ):
        return "L2"
    # L1：工作区内可逆 git 操作
    if executable == "git" and len(parts) >= 3 and parts[1] == "checkout" and parts[2] == "-b":
        return "L1"
    if executable == "git" and len(parts) >= 2 and parts[1] == "add":
        return "L1"
    if executable == "snapshot":
        return "L1"
    safe_l0_commands = {
        "pwd",
    }
    if executable in safe_l0_commands:
        return "L0"
    return "L2"


def auto_approve_allowed(risk_level: str) -> bool:
    """L3 绝不允许自动通过（FR-203 / §17.2）。"""
    return risk_level in {"L0", "L1"}
