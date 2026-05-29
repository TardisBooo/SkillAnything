"""X official API connector."""

from __future__ import annotations

import re
from urllib.parse import urlencode, urlparse

from skillanything.config import Settings
from skillanything.connectors.base import Connector, ConnectorError, FetchRequest
from skillanything.connectors.http import fetch_json
from skillanything.models import CollectResult, ContentItem, MediaAsset, Profile, Segment
from skillanything.utils import stable_id


class XConnector(Connector):
    name = "x"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def can_handle(self, request: FetchRequest) -> bool:
        host = urlparse(request.source).netloc.lower()
        return request.platform in {"x", "twitter"} or host in {"x.com", "twitter.com", "www.x.com"}

    def collect(self, request: FetchRequest) -> CollectResult:
        if not self.settings.x_bearer_token:
            raise ConnectorError("X_BEARER_TOKEN is required for the official X API connector")
        username = self._username_from_url(request.source)
        user = self._get_user(username)
        profile = Profile(
            id=stable_id("x", username),
            platform="x",
            profile_url=request.source,
            handle=username,
            display_name=user.get("name") or username,
            description=user.get("description"),
            raw=user,
        )
        timeline = self._get_tweets(user["id"], request.max_items)
        media_by_key = {
            media["media_key"]: media for media in timeline.get("includes", {}).get("media", [])
        }
        items: list[ContentItem] = []
        assets: list[MediaAsset] = []
        segments: list[Segment] = []
        for index, tweet in enumerate(timeline.get("data", []), start=1):
            item_id = stable_id("x", profile.id, tweet["id"])
            text = tweet.get("text", "")
            item = ContentItem(
                id=item_id,
                profile_id=profile.id,
                platform="x",
                source_id=tweet["id"],
                url=f"https://x.com/{username}/status/{tweet['id']}",
                title=text.splitlines()[0][:120] if text else f"Post {tweet['id']}",
                author=username,
                published_at=tweet.get("created_at"),
                text=text,
                metrics=tweet.get("public_metrics", {}),
                raw=tweet,
            )
            items.append(item)
            segments.append(
                Segment(
                    id=stable_id(item_id, "x", "text"),
                    item_id=item_id,
                    source="x",
                    position=str(index),
                    text=text,
                )
            )
            if request.include_media:
                for media_key in tweet.get("attachments", {}).get("media_keys", []):
                    media = media_by_key.get(media_key, {})
                    assets.append(
                        MediaAsset(
                            id=stable_id(item_id, "media", media_key),
                            item_id=item_id,
                            kind=media.get("type", "media"),
                            url=media.get("url") or media.get("preview_image_url"),
                            metadata=media,
                        )
                    )
        return CollectResult(
            profile=profile,
            items=items,
            assets=assets,
            segments=segments,
            diagnostics=[f"x_user_id={user['id']}", f"tweets={len(items)}"],
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.x_bearer_token}"}

    def _get_user(self, username: str) -> dict:
        qs = urlencode({"user.fields": "description,created_at,public_metrics,verified"})
        data = fetch_json(
            f"https://api.x.com/2/users/by/username/{username}?{qs}",
            headers=self._headers(),
        )
        if "data" not in data:
            raise ConnectorError(f"X user lookup failed: {data}")
        return data["data"]

    def _get_tweets(self, user_id: str, max_items: int) -> dict:
        qs = urlencode(
            {
                "max_results": max(5, min(max_items, 100)),
                "exclude": "replies",
                "expansions": "attachments.media_keys,referenced_tweets.id,author_id",
                "tweet.fields": "created_at,public_metrics,conversation_id,attachments,entities",
                "media.fields": "url,preview_image_url,type,width,height,duration_ms,alt_text",
            }
        )
        data = fetch_json(
            f"https://api.x.com/2/users/{user_id}/tweets?{qs}",
            headers=self._headers(),
        )
        if "errors" in data and "data" not in data:
            raise ConnectorError(f"X timeline lookup failed: {data}")
        return data

    @staticmethod
    def _username_from_url(source: str) -> str:
        match = re.search(r"(?:x|twitter)\.com/([^/?#]+)", source, re.I)
        if not match:
            raise ConnectorError(f"cannot parse X username from {source}")
        username = match.group(1).strip("@")
        if username in {"home", "search", "i"}:
            raise ConnectorError(f"not an X profile URL: {source}")
        return username
