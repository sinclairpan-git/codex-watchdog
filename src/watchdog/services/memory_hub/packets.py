from __future__ import annotations

from watchdog.services.memory_hub.models import (
    ContextQualitySnapshot,
    PacketInputRef,
    WorkerScopedPacketInput,
)


def build_packet_inputs(
    *,
    refs: list[PacketInputRef],
    quality: ContextQualitySnapshot,
    worker_scope: WorkerScopedPacketInput | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "refs": [ref.model_dump(mode="json") for ref in refs],
        "quality": quality.model_dump(mode="json"),
    }
    if worker_scope is not None:
        payload["worker_scope"] = worker_scope.model_dump(mode="json")
    return payload
