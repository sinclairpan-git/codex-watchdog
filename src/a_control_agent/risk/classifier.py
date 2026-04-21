"""命令字符串 → L0–L3 启发式分级（PRD §7，可替换为更强策略）。"""

from __future__ import annotations

import re
import shlex


_SAFE_FILE_PERMISSIONS = {"fs.read", "fs.write"}
_PYTEST_PATH_FLAGS = {"--rootdir", "--basetemp", "--confcutdir", "-c"}


def _normalized_command_tokens(command: str) -> list[str]:
    normalized: list[str] = []
    for token in _split_command(command):
        head = token.split("=", 1)[0]
        normalized.append(head.lstrip("-").lower())
    return normalized


def _contains_command_word(command: str, marker: str) -> bool:
    return (
        re.search(
            rf"(^|[\s\"';|&()])(?:[^\s\"';|&()]+/)*{re.escape(marker)}\b",
            command,
        )
        is not None
    )


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _classify_permissions_request(command: str) -> str | None:
    prefix = "permissions:"
    if not command.startswith(prefix):
        return None
    raw_permissions = command[len(prefix) :]
    if not raw_permissions:
        return "L2"
    permissions = [item.strip() for item in raw_permissions.split(",")]
    if any(not item for item in permissions):
        return "L2"
    if any(item.startswith("credentials.") for item in permissions):
        return "L3"
    if any(item.startswith("network.") for item in permissions):
        return "L2"
    if all(item in _SAFE_FILE_PERMISSIONS for item in permissions):
        return "L1"
    return "L2"


def _is_path_boundary_escape(arg: str) -> bool:
    normalized = arg.strip().lower()
    if not normalized:
        return False
    if normalized.startswith(("/", "~")):
        return True
    if re.match(r"^[a-z]:[\\/]", normalized):
        return True
    return normalized in {"..", "."} or normalized.startswith("../") or normalized.startswith("..\\")


def _is_safe_local_pytest_command(command: str) -> bool:
    tokens = _split_command(command)
    if not tokens:
        return False

    executable = tokens[0].rsplit("/", 1)[-1].lower()
    args: list[str]
    if executable == "pytest":
        args = tokens[1:]
    elif executable in {"python", "python3"} and len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] == "pytest":
        args = tokens[3:]
    elif executable == "uv" and len(tokens) >= 3 and tokens[1] == "run" and tokens[2] == "pytest":
        args = tokens[3:]
    else:
        return False

    expect_flag_value = False
    for arg in args:
        if expect_flag_value:
            expect_flag_value = False
            return False
        if arg in _PYTEST_PATH_FLAGS:
            expect_flag_value = True
            continue
        if any(arg.startswith(f"{flag}=") for flag in _PYTEST_PATH_FLAGS):
            return False
        if _is_path_boundary_escape(arg):
            return False
        if not arg.startswith("-"):
            if re.fullmatch(r"[A-Za-z0-9_./:\-\[\]]+", arg) is None:
                return False
    return not expect_flag_value


def classify_risk(command: str) -> str:
    c = command.lower().strip()
    if not c:
        return "L2"
    permission_risk = _classify_permissions_request(c)
    if permission_risk is not None:
        return permission_risk
    parts = c.split()
    first_token = parts[0] if parts else ""
    executable = first_token.rsplit("/", 1)[-1]
    # L3：高敏感 / 发布 / 破坏性 / 凭证
    l3_phrase_markers = (
        "rm -rf",
        "git push",
        "绕过",
        "绕过审批",
        "sandbox off",
        "sudo ",
        "chmod 777",
        "/etc/",
        "launchctl",
    )
    l3_token_markers = (
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
    if any(m in c for m in l3_phrase_markers):
        return "L3"
    command_tokens = _normalized_command_tokens(c)
    if any(marker in command_tokens for marker in l3_token_markers):
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
    if _is_safe_local_pytest_command(c):
        return "L0"
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
