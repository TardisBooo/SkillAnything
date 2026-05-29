"""Domain models shared by collectors, distillers, and packagers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Citation:
    source_url: str
    item_id: str
    quote: str
    position: str | None = None
    asset_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Profile:
    id: str
    platform: str
    profile_url: str
    handle: str | None = None
    display_name: str | None = None
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContentItem:
    id: str
    profile_id: str
    platform: str
    source_id: str | None
    url: str
    title: str
    author: str | None = None
    published_at: str | None = None
    text: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MediaAsset:
    id: str
    item_id: str
    kind: str
    url: str | None = None
    local_path: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Segment:
    id: str
    item_id: str
    source: str
    position: str
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Comment:
    id: str
    item_id: str
    author: str | None
    text: str
    published_at: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProfileBundle:
    profile: Profile
    items: list[ContentItem] = field(default_factory=list)
    assets: list[MediaAsset] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "assets": [asset.to_dict() for asset in self.assets],
            "segments": [segment.to_dict() for segment in self.segments],
            "comments": [comment.to_dict() for comment in self.comments],
        }


@dataclass(slots=True)
class CollectResult:
    profile: Profile
    items: list[ContentItem] = field(default_factory=list)
    assets: list[MediaAsset] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DistilledSkill:
    id: str
    profile_id: str
    title: str
    version: str
    summary: str
    principles: list[str]
    workflow: list[str]
    style_rules: list[str]
    blindspots: list[str]
    eval_cases: list[dict[str, Any]]
    citations: list[Citation]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["citations"] = [citation.to_dict() for citation in self.citations]
        return data
