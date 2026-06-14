"""Adapters from existing collector models to the source-layer IR."""

from __future__ import annotations

from skillanything.ir import Corpus, SourceDocument, corpus_from_bundle, source_document_from_item
from skillanything.models import CollectResult, ProfileBundle


def collect_result_to_documents(result: CollectResult) -> list[SourceDocument]:
    assets_by_item = _group_by_item(result.assets)
    segments_by_item = _group_by_item(result.segments)
    comments_by_item = _group_by_item(result.comments)
    return [
        source_document_from_item(
            item,
            assets=assets_by_item.get(item.id, []),
            segments=segments_by_item.get(item.id, []),
            comments=comments_by_item.get(item.id, []),
        )
        for item in result.items
    ]


def bundle_to_corpus(
    bundle: ProfileBundle,
    *,
    goal: str = "",
    item_limit: int | None = None,
) -> Corpus:
    return corpus_from_bundle(bundle, goal=goal, item_limit=item_limit)


def _group_by_item(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row.item_id, []).append(row)
    return grouped
