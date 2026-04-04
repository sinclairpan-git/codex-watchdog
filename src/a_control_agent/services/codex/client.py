from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CodexClient(Protocol):
    """未来对接 Codex app-server 的最小协议面；默认实现不发起网络请求。"""

    def ping(self) -> bool:
        """控制面可达性探测（占位）。"""
        ...

    def describe_thread(self, thread_id: str) -> dict[str, Any]:
        """线程元数据摘要（占位）。"""
        ...


class NoOpCodexClient:
    """默认空实现：供未配置 Codex 时保持服务可启动。"""

    def ping(self) -> bool:
        return True

    def describe_thread(self, thread_id: str) -> dict[str, Any]:
        return {"thread_id": thread_id, "connected": False, "note": "no_codex_backend"}
