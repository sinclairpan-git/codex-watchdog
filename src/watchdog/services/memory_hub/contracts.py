from __future__ import annotations

from typing import Literal


MemoryFallbackMode = Literal["session_service_runtime_snapshot", "reference_only"]
MemoryProviderOperation = Literal["search", "store", "manage"]
MemoryPreviewContractName = Literal["user-model", "periodic-nudge", "ai-autosdlc-cursor"]
ResidentWriteOperation = Literal["add", "replace", "remove"]
SecurityVerdict = Literal["pass", "caution", "warn", "dangerous", "quarantine"]
SkillSourceKind = Literal["local", "shared", "external"]
