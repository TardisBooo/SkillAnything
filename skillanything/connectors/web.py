"""Plain webpage connector."""

from __future__ import annotations

from urllib.parse import urljoin

from skillanything.connectors.base import Connector, FetchRequest
from skillanything.connectors.http import fetch_text
from skillanything.extract.text import extract_image_urls, html_title, html_to_text
from skillanything.models import CollectResult, ContentItem, MediaAsset, Profile, Segment
from skillanything.utils import stable_id


class WebConnector(Connector):
    name = "web"

    def can_handle(self, request: FetchRequest) -> bool:
        return request.source.startswith(("http://", "https://"))

    def collect(self, request: FetchRequest) -> CollectResult:
        raw = fetch_text(request.source)
        title = html_title(raw) or request.source
        text = html_to_text(raw)
        platform = request.platform or "web"
        profile = Profile(
            id=stable_id(platform, request.source),
            platform=platform,
            profile_url=request.source,
            display_name=title,
            raw={"source_kind": "webpage"},
        )
        item_id = stable_id(platform, profile.id, request.source)
        item = ContentItem(
            id=item_id,
            profile_id=profile.id,
            platform=platform,
            source_id=request.source,
            url=request.source,
            title=title,
            text=text,
            raw={"html_length": len(raw)},
        )
        assets = [
            MediaAsset(
                id=stable_id(item_id, "image", image_url),
                item_id=item_id,
                kind="image",
                url=urljoin(request.source, image_url),
            )
            for image_url in extract_image_urls(raw)
        ]
        segments = [
            Segment(
                id=stable_id(item_id, "web", "body"),
                item_id=item_id,
                source="web",
                position="body",
                text=text,
            )
        ]
        return CollectResult(
            profile=profile,
            items=[item],
            assets=assets if request.include_media else [],
            segments=segments,
            diagnostics=[f"html_length={len(raw)}"],
        )
