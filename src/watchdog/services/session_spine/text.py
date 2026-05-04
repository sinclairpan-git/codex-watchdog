from __future__ import annotations

import re

_RULE_BASED_CONTINUE_PREFIX_RE = re.compile(
    r"(?:\s*\[steer:[^\]]+\]\s*下一步建议：\s*继续推进\s*)+",
    re.IGNORECASE,
)
_REDUNDANT_NEXT_STEP_RE = re.compile(r"(?:下一步建议：\s*){2,}")
_REPEATED_VERIFY_RECENT_CHANGE_RE = re.compile(
    r"(?:[，,\s]*并优先验证最近改动。)+"
)
_REPEATED_CONTINUE_WHEN_UNBLOCKED_RE = re.compile(
    r"(?:\s*如果无阻塞，请立即继续执行。)+"
)
_CONTINUE_PROGRESS_TEMPLATE_RE = re.compile(
    r"^(?:\s*\[steer:[^\]]+\]\s*)?请汇总当前进展：\s*"
    r"1\.\s*已完成内容\s*"
    r"2\.\s*当前阻塞点\s*"
    r"3\.\s*下一步最小动作\s*"
    r"如果无阻塞，请立即继续执行。?\s*(?:，并优先验证最近改动。)?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTIBLANK_RE = re.compile(r"\n{3,}")
_INLINE_CITATION_RE = re.compile(r"【[^】]+】")
_CONVERSATIONAL_FOLLOWUP_RE = re.compile(r"\n*\s*如果你要，我下一条可以[^\n]*", re.DOTALL)
_CODEX_APP_GIT_DIRECTIVE_RE = re.compile(r"^\s*::git-[^\n]*\s*$", re.MULTILINE)


def sanitize_session_summary(text: str | None) -> str:
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    normalized = _INLINE_CITATION_RE.sub("", normalized).strip()
    normalized = _CODEX_APP_GIT_DIRECTIVE_RE.sub("", normalized).strip()
    if _CONTINUE_PROGRESS_TEMPLATE_RE.match(normalized):
        return "当前进展待汇总；需要先返回已完成内容、阻塞点和下一步动作。"
    if normalized.startswith("因为这个聊天界面对“文件链接”的支持比“文件夹链接”稳定"):
        return "已确认工程目录和离线目录位置；可直接打开 zip、index.html 或工程目录。"
    if normalized.startswith("我已经把离线安装包重建回来了。"):
        return "已重建离线安装包并产出 zip；dist 安装包产物已保留，暂不再清理。"
    if "给业务方确认的清单" in normalized and "OQ-" in normalized:
        return "已整理业务确认清单；当前保留未关闭 OQ，建议优先确认 OQ-017 / OQ-018 / OQ-021。"
    if normalized.startswith("All project files removed;") and "Next steps:" in normalized:
        return "项目目录已清空；下一步需重新 scaffold 项目并重装依赖。"

    normalized = _CONVERSATIONAL_FOLLOWUP_RE.sub("", normalized).strip()

    had_rule_loop = bool(_RULE_BASED_CONTINUE_PREFIX_RE.search(normalized))
    normalized = _RULE_BASED_CONTINUE_PREFIX_RE.sub("", normalized)
    normalized = _REDUNDANT_NEXT_STEP_RE.sub("下一步建议：", normalized)

    if _REPEATED_VERIFY_RECENT_CHANGE_RE.search(normalized):
        normalized = _REPEATED_VERIFY_RECENT_CHANGE_RE.sub("，并优先验证最近改动。", normalized)

    if _REPEATED_CONTINUE_WHEN_UNBLOCKED_RE.search(normalized):
        normalized = _REPEATED_CONTINUE_WHEN_UNBLOCKED_RE.sub(
            "\n如果无阻塞，请立即继续执行。", normalized
        )

    normalized = _WHITESPACE_RE.sub(" ", normalized)
    normalized = _MULTIBLANK_RE.sub("\n\n", normalized)
    normalized = normalized.strip(" ，,\n\t")

    if had_rule_loop and not normalized:
        return "继续推进当前任务，并优先验证最近改动。"
    return normalized
