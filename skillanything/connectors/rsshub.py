"""RSSHub-backed connector for finance/community sources."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

from skillanything.config import Settings
from skillanything.connectors.base import Connector, ConnectorError, FetchRequest
from skillanything.connectors.http import fetch_text
from skillanything.extract.text import extract_image_urls, html_to_text
from skillanything.models import CollectResult, ContentItem, MediaAsset, Profile, Segment
from skillanything.utils import stable_id


class RSSHubConnector(Connector):
    name = "rsshub"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def can_handle(self, request: FetchRequest) -> bool:
        if request.source.startswith(("http://", "https://")):
            host = urlparse(request.source).netloc.lower()
            return (
                "rsshub" in host
                or "xueqiu.com" in host
                or "taoguba" in host
                or "tgb.cn" in host
                or "jiuyangongshe" in host
                or "bilibili.com" in host
                or request.platform in {"xueqiu", "taoguba", "jiuyangongshe", "bilibili"}
            )
        return request.source.startswith("/")

    def collect(self, request: FetchRequest) -> CollectResult:
        feed_url, platform, handle = self._feed_url(request)
        raw = fetch_text(feed_url)
        entries = self._parse_entries(raw)
        if not entries:
            raise ConnectorError(f"RSSHub returned no entries for {feed_url}")

        profile = Profile(
            id=stable_id(platform, request.source),
            platform=platform,
            profile_url=request.source,
            handle=handle,
            display_name=handle or platform,
            raw={"feed_url": feed_url},
        )
        items: list[ContentItem] = []
        assets: list[MediaAsset] = []
        segments: list[Segment] = []

        for index, entry in enumerate(entries[: request.max_items], start=1):
            html_body = entry.get("content") or entry.get("description") or ""
            text = html_to_text(html_body)
            source_url = entry.get("link") or feed_url
            source_id = entry.get("guid") or source_url
            item_id = stable_id(platform, profile.id, source_id)
            item = ContentItem(
                id=item_id,
                profile_id=profile.id,
                platform=platform,
                source_id=source_id,
                url=source_url,
                title=entry.get("title") or f"{platform} item {index}",
                author=entry.get("author") or handle,
                published_at=entry.get("published_at"),
                text=text,
                raw={"rss": entry, "feed_url": feed_url},
            )
            items.append(item)
            if text:
                segments.append(
                    Segment(
                        id=stable_id(item_id, "rss", index),
                        item_id=item_id,
                        source="rss",
                        position=str(index),
                        text=text,
                        metadata={"feed_url": feed_url},
                    )
                )
            if request.include_media:
                for asset_index, image_url in enumerate(extract_image_urls(html_body), start=1):
                    assets.append(
                        MediaAsset(
                            id=stable_id(item_id, "image", image_url),
                            item_id=item_id,
                            kind="image",
                            url=urljoin(source_url, image_url),
                            metadata={"position": asset_index},
                        )
                    )

        return CollectResult(
            profile=profile,
            items=items,
            assets=assets,
            segments=segments,
            diagnostics=[f"rsshub_feed={feed_url}", f"entries={len(entries)}"],
        )

    def _feed_url(self, request: FetchRequest) -> tuple[str, str, str | None]:
        source = request.source.strip()
        if source.startswith(("http://", "https://")) and "rsshub" in urlparse(source).netloc:
            platform = request.platform or self._platform_from_route(urlparse(source).path)
            return source, platform, None
        if source.startswith("/"):
            platform = request.platform or self._platform_from_route(source)
            return f"{self.settings.rsshub_base}{source}", platform, None

        route, platform, handle = self._route_from_profile(source, request.platform)
        return f"{self.settings.rsshub_base}{route}", platform, handle

    @staticmethod
    def _platform_from_route(route: str) -> str:
        parts = [part for part in route.split("/") if part]
        return parts[0] if parts else "rsshub"

    @staticmethod
    def _route_from_profile(source: str, platform_hint: str | None) -> tuple[str, str, str | None]:
        lowered = source.lower()
        if platform_hint == "jiuyangongshe" or "jiuyangongshe" in lowered:
            return "/jiuyangongshe/community", "jiuyangongshe", "community"

        match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", source, re.I)
        if match or platform_hint == "xueqiu":
            user_id = match.group(1) if match else source.rstrip("/").split("/")[-1]
            return f"/xueqiu/user/{user_id}", "xueqiu", user_id

        match = re.search(r"(?:taoguba|tgb)\.[^/]+/(?:blog/)?(\d+)", source, re.I)
        if match or platform_hint == "taoguba":
            user_id = match.group(1) if match else source.rstrip("/").split("/")[-1]
            return f"/taoguba/blog/{user_id}", "taoguba", user_id

        match = re.search(r"space\.bilibili\.com/(\d+)", source, re.I)
        if match or platform_hint == "bilibili":
            user_id = match.group(1) if match else source.rstrip("/").split("/")[-1]
            return f"/bilibili/user/video/{user_id}", "bilibili", user_id

        raise ConnectorError(f"cannot map source to RSSHub route: {source}")

    @staticmethod
    def _parse_entries(raw_xml: str) -> list[dict[str, str]]:
        root = ET.fromstring(raw_xml)
        entries: list[dict[str, str]] = []

        for node in root.findall(".//item"):
            entries.append(
                {
                    "title": _child_text(node, "title"),
                    "link": _child_text(node, "link"),
                    "guid": _child_text(node, "guid"),
                    "published_at": _child_text(node, "pubDate") or _child_text(node, "dc:date"),
                    "description": _child_text(node, "description"),
                    "content": _child_text(node, "content:encoded"),
                    "author": _child_text(node, "author") or _child_text(node, "dc:creator"),
                }
            )

        atom_ns = "{http://www.w3.org/2005/Atom}"
        for node in root.findall(f".//{atom_ns}entry"):
            link = ""
            link_node = node.find(f"{atom_ns}link")
            if link_node is not None:
                link = link_node.attrib.get("href", "")
            entries.append(
                {
                    "title": _node_text(node.find(f"{atom_ns}title")),
                    "link": link,
                    "guid": _node_text(node.find(f"{atom_ns}id")),
                    "published_at": _node_text(node.find(f"{atom_ns}updated")),
                    "description": _node_text(node.find(f"{atom_ns}summary")),
                    "content": _node_text(node.find(f"{atom_ns}content")),
                    "author": "",
                }
            )
        return entries


def _child_text(node: ET.Element, tag: str) -> str:
    if ":" in tag:
        suffix = tag.split(":", 1)[1]
        for child in node:
            if child.tag.endswith(f"}}{suffix}") or child.tag == tag:
                return _node_text(child)
        return ""
    child = node.find(tag)
    return _node_text(child)


def _node_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()
