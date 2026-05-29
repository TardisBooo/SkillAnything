"""Local file import connector."""

from __future__ import annotations

from pathlib import Path

from skillanything.connectors.base import Connector, ConnectorError, FetchRequest
from skillanything.extract.text import html_to_text
from skillanything.models import CollectResult, ContentItem, Profile, Segment
from skillanything.utils import stable_id


class FileConnector(Connector):
    name = "file"

    def can_handle(self, request: FetchRequest) -> bool:
        return Path(request.source).expanduser().exists()

    def collect(self, request: FetchRequest) -> CollectResult:
        path = Path(request.source).expanduser().resolve()
        if not path.is_file():
            raise ConnectorError(f"file import expects a file path: {path}")
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = html_to_text(raw) if path.suffix.lower() in {".html", ".htm"} else raw.strip()
        platform = request.platform or "file"
        profile = Profile(
            id=stable_id(platform, str(path)),
            platform=platform,
            profile_url=str(path),
            display_name=path.stem,
            raw={"source_kind": "file", "path": str(path)},
        )
        item_id = stable_id(platform, profile.id, str(path))
        item = ContentItem(
            id=item_id,
            profile_id=profile.id,
            platform=platform,
            source_id=str(path),
            url=str(path),
            title=path.stem,
            text=text,
            raw={"file_size": path.stat().st_size, "suffix": path.suffix.lower()},
        )
        segment = Segment(
            id=stable_id(item_id, "file", "body"),
            item_id=item_id,
            source="file",
            position="body",
            text=text,
        )
        return CollectResult(profile=profile, items=[item], segments=[segment])
