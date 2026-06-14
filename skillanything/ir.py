"""Canonical intermediate representation for SkillAnything.

The IR keeps collectors, distillers, reviewers, and exporters decoupled.  The
existing ProfileBundle/DistilledSkill models remain supported; helper functions
adapt them into this more general shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from skillanything.models import (
    Citation,
    Comment,
    ContentItem,
    DistilledSkill,
    MediaAsset,
    ProfileBundle,
    Segment,
)
from skillanything.utils import stable_id, utc_now


@dataclass(slots=True)
class SourceAssetRef:
    id: str
    kind: str
    url: str | None = None
    local_path: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceSegmentRef:
    id: str
    source: str
    position: str
    text: str
    asset_id: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceDocument:
    id: str
    profile_id: str
    platform: str
    url: str
    title: str
    source_id: str | None = None
    author: str | None = None
    published_at: str | None = None
    text: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    assets: list[SourceAssetRef] = field(default_factory=list)
    segments: list[SourceSegmentRef] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityRequest:
    id: str
    label: str
    type: str = "analysis_method"
    instructions: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    origin: str = "user"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Corpus:
    id: str
    profile_id: str
    title: str
    goal: str = ""
    source_ids: list[str] = field(default_factory=list)
    documents: list[SourceDocument] = field(default_factory=list)
    capability_requests: list[CapabilityRequest] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidenceLink:
    id: str
    doc_id: str | None = None
    item_id: str | None = None
    segment_id: str | None = None
    source_url: str | None = None
    quote: str = ""
    support_type: str = "supports"
    tier: str = "source"
    confidence: float = 0.6
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Capability:
    id: str
    corpus_id: str
    profile_id: str
    name: str
    type: str
    summary: str
    principles: list[str] = field(default_factory=list)
    workflow: list[str] = field(default_factory=list)
    style_rules: list[str] = field(default_factory=list)
    blindspots: list[str] = field(default_factory=list)
    evidence: list[EvidenceLink] = field(default_factory=list)
    eval_cases: list[dict[str, Any]] = field(default_factory=list)
    origin: str = "auto"
    confidence: float = 0.6
    review_state: str = "draft"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SkillPack:
    id: str
    capability_id: str
    profile_id: str
    skill_id: str
    title: str
    version: str = "0.1.0"
    target_surfaces: list[str] = field(default_factory=lambda: ["codex-skill"])
    skill_json: dict[str, Any] = field(default_factory=dict)
    capability: dict[str, Any] = field(default_factory=dict)
    corpus: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def capability_request_from_focus(
    focus: str,
    *,
    capability_type: str = "analysis_method",
    origin: str = "user",
    schema: dict[str, Any] | None = None,
) -> CapabilityRequest:
    label = focus.strip() or capability_type
    return CapabilityRequest(
        id=stable_id("capability-request", capability_type, label, origin),
        label=label,
        type=capability_type,
        instructions=focus.strip(),
        schema=schema or {},
        origin=origin,
    )


def source_document_from_item(
    item: ContentItem,
    assets: list[MediaAsset] | None = None,
    segments: list[Segment] | None = None,
    comments: list[Comment] | None = None,
) -> SourceDocument:
    return SourceDocument(
        id=item.id,
        profile_id=item.profile_id,
        platform=item.platform,
        source_id=item.source_id,
        url=item.url,
        title=item.title,
        author=item.author,
        published_at=item.published_at,
        text=item.text,
        metrics=dict(item.metrics),
        raw=dict(item.raw),
        assets=[
            SourceAssetRef(
                id=asset.id,
                kind=asset.kind,
                url=asset.url,
                local_path=asset.local_path,
                mime_type=asset.mime_type,
                metadata=dict(asset.metadata),
            )
            for asset in assets or []
        ],
        segments=[
            SourceSegmentRef(
                id=segment.id,
                source=segment.source,
                position=segment.position,
                text=segment.text,
                asset_id=str(segment.metadata.get("asset_id") or "") or None,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                metadata=dict(segment.metadata),
            )
            for segment in segments or []
        ],
        comments=[comment.to_dict() for comment in comments or []],
        metadata={"created_at": item.created_at, "updated_at": item.updated_at},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def corpus_from_bundle(
    bundle: ProfileBundle,
    *,
    goal: str = "",
    item_limit: int | None = None,
    capability_requests: list[CapabilityRequest] | None = None,
) -> Corpus:
    items = bundle.items[:item_limit] if item_limit is not None else list(bundle.items)
    assets_by_item = _group_by_item(bundle.assets)
    segments_by_item = _group_by_item(bundle.segments)
    comments_by_item = _group_by_item(bundle.comments)
    documents = [
        source_document_from_item(
            item,
            assets=assets_by_item.get(item.id, []),
            segments=segments_by_item.get(item.id, []),
            comments=comments_by_item.get(item.id, []),
        )
        for item in items
    ]
    profile = bundle.profile
    title = profile.display_name or profile.handle or profile.id
    corpus_id = stable_id(
        "corpus",
        profile.id,
        goal,
        "|".join(document.id for document in documents),
        len(bundle.segments),
        len(bundle.comments),
    )
    return Corpus(
        id=corpus_id,
        profile_id=profile.id,
        title=str(title),
        goal=goal,
        source_ids=[document.id for document in documents],
        documents=documents,
        capability_requests=capability_requests or [],
        metadata={
            "profile": profile.to_dict(),
            "counts": {
                "documents": len(documents),
                "assets": sum(len(document.assets) for document in documents),
                "segments": sum(len(document.segments) for document in documents),
                "comments": sum(len(document.comments) for document in documents),
            },
        },
    )


def capability_from_skill(
    skill: DistilledSkill | dict[str, Any],
    *,
    corpus_id: str,
    capability_type: str = "analysis_method",
    origin: str = "auto",
    request: CapabilityRequest | None = None,
) -> Capability:
    data = skill.to_dict() if isinstance(skill, DistilledSkill) else dict(skill)
    profile_id = str(data.get("profile_id") or "")
    citations = _citations_from_skill(data.get("citations", []))
    evidence = [
        EvidenceLink(
            id=stable_id("evidence", corpus_id, citation.item_id, citation.quote, index),
            doc_id=citation.item_id,
            item_id=citation.item_id,
            segment_id=citation.asset_id,
            source_url=citation.source_url,
            quote=citation.quote,
            confidence=0.72 if citation.quote else 0.55,
            metadata={"position": citation.position, "asset_id": citation.asset_id},
        )
        for index, citation in enumerate(citations)
    ]
    name = str(data.get("title") or request.label if request else data.get("title") or "Capability")
    capability_id = stable_id(
        "capability",
        corpus_id,
        profile_id,
        capability_type,
        origin,
        name,
        request.id if request else "",
    )
    confidence = min(0.92, 0.54 + min(len(evidence), 8) * 0.04)
    return Capability(
        id=capability_id,
        corpus_id=corpus_id,
        profile_id=profile_id,
        name=name,
        type=capability_type,
        summary=str(data.get("summary") or ""),
        principles=[str(item) for item in data.get("principles", [])],
        workflow=[str(item) for item in data.get("workflow", [])],
        style_rules=[str(item) for item in data.get("style_rules", [])],
        blindspots=[str(item) for item in data.get("blindspots", [])],
        evidence=evidence,
        eval_cases=list(data.get("eval_cases", [])),
        origin=origin,
        confidence=confidence,
        review_state="draft",
        metadata={
            "skill_id": data.get("id"),
            "distiller_metadata": data.get("metadata", {}),
            "request": request.to_dict() if request else None,
        },
    )


def skill_pack_from_capability(
    capability: Capability,
    skill: DistilledSkill | dict[str, Any],
    corpus: Corpus | dict[str, Any],
    *,
    target_surfaces: list[str] | None = None,
) -> SkillPack:
    skill_json = skill.to_dict() if isinstance(skill, DistilledSkill) else dict(skill)
    corpus_json = corpus.to_dict() if isinstance(corpus, Corpus) else dict(corpus)
    pack_id = stable_id(
        "skill-pack",
        capability.id,
        skill_json.get("id"),
        ",".join(target_surfaces or ["codex-skill"]),
    )
    return SkillPack(
        id=pack_id,
        capability_id=capability.id,
        profile_id=capability.profile_id,
        skill_id=str(skill_json.get("id") or ""),
        title=capability.name,
        version=str(skill_json.get("version") or "0.1.0"),
        target_surfaces=target_surfaces or ["codex-skill"],
        skill_json=skill_json,
        capability=capability.to_dict(),
        corpus=corpus_json,
        metadata={
            "artifact_schema": "skillanything.skill_pack.v1",
            "evidence_count": len(capability.evidence),
        },
    )


def _group_by_item(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.item_id, []).append(row)
    return grouped


def _citations_from_skill(rows: list[Any]) -> list[Citation]:
    citations: list[Citation] = []
    for row in rows:
        if isinstance(row, Citation):
            citations.append(row)
            continue
        if not isinstance(row, dict):
            continue
        citations.append(
            Citation(
                source_url=str(row.get("source_url") or ""),
                item_id=str(row.get("item_id") or row.get("doc_id") or ""),
                quote=str(row.get("quote") or ""),
                position=row.get("position"),
                asset_id=row.get("asset_id") or row.get("segment_id"),
            )
        )
    return citations
