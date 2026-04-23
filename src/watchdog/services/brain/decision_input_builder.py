from __future__ import annotations

from watchdog.services.brain.models import DecisionPacketInput


class DecisionInputBuilder:
    def build(
        self,
        *,
        packet_version: str,
        refs: list[dict[str, object]],
        quality: dict[str, object],
        provenance: dict[str, object] | None = None,
        freshness: dict[str, object] | None = None,
    ) -> DecisionPacketInput:
        return DecisionPacketInput(
            packet_version=packet_version,
            refs=refs,
            quality=quality,
            provenance=provenance or {},
            freshness=freshness or {},
        )

