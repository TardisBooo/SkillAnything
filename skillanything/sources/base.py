"""Source layer extension contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from skillanything.ir import SourceDocument


@dataclass(slots=True)
class SourceEnvelope:
    """Uniform source payload passed upward to corpus/distillation services."""

    source_id: str
    platform: str
    documents: list[SourceDocument]
    diagnostics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    """Adapter protocol for custom data sources."""

    name: str

    def can_handle(self, source: str, platform: str | None = None) -> bool:
        """Return whether this adapter can normalize the source."""

    def collect(self, source: str, platform: str | None = None, **kwargs: Any) -> SourceEnvelope:
        """Collect and normalize a source into SourceDocuments."""
