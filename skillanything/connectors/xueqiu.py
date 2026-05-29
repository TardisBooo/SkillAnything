"""Text-only Xueqiu connector."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from typing import Any

from skillanything.config import Settings
from skillanything.connectors.base import Connector, ConnectorError, FetchRequest
from skillanything.connectors.http import DEFAULT_UA
from skillanything.extract.text import html_to_text, normalize_text
from skillanything.models import CollectResult, ContentItem, Profile, Segment
from skillanything.utils import stable_id, truncate

ROOT_URL = "https://xueqiu.com"


class XueqiuConnector(Connector):
    """Collect public Xueqiu user posts as text.

    Xueqiu exposes the first timeline page after a normal profile visit. Additional pages often
    require a logged-in cookie, so this connector supports SKILLANYTHING_XUEQIU_COOKIE and records
    a diagnostic when it has to stop early.
    """

    name = "xueqiu"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def can_handle(self, request: FetchRequest) -> bool:
        if request.platform == "xueqiu":
            return True
        if not request.source.startswith(("http://", "https://")):
            return False
        host = urllib.parse.urlparse(request.source).netloc.lower()
        return host.endswith("xueqiu.com")

    def collect(self, request: FetchRequest) -> CollectResult:
        user_id = _user_id_from_source(request.source)
        type_id = _type_from_source(request.source)
        profile_url = f"{ROOT_URL}/u/{user_id}"
        opener = _opener()
        headers = _headers(profile_url, self.settings.xueqiu_cookie)

        profile_html = _read_text(opener, profile_url, headers)
        profile_meta = _profile_meta(profile_html, user_id)
        profile = Profile(
            id=stable_id("xueqiu", user_id),
            platform="xueqiu",
            profile_url=request.source,
            handle=user_id,
            display_name=profile_meta.get("screen_name") or user_id,
            description=profile_meta.get("description"),
            raw={
                "source_kind": "xueqiu_user",
                "user_id": user_id,
                "type": type_id,
            },
        )

        statuses: list[dict[str, Any]] = []
        diagnostics = [f"user_id={user_id}", f"type={type_id}"]
        page = 1
        total: int | None = None
        max_page: int | None = None
        while len(statuses) < request.max_items:
            try:
                data = _fetch_timeline(opener, headers, user_id, type_id, page)
            except ConnectorError as exc:
                diagnostics.append(str(exc))
                break
            if total is None:
                total = _as_int(data.get("total"))
                max_page = _as_int(data.get("maxPage"))
                if total is not None:
                    diagnostics.append(f"total={total}")
                if max_page is not None:
                    diagnostics.append(f"max_page={max_page}")
            page_statuses = [
                status for status in data.get("statuses", []) if isinstance(status, dict)
            ]
            page_statuses = [status for status in page_statuses if status.get("mark") != 1]
            if not page_statuses:
                break
            before = len(statuses)
            seen_ids = {str(status.get("id")) for status in statuses}
            for status in page_statuses:
                if len(statuses) >= request.max_items:
                    break
                status_id = str(status.get("id") or "")
                if status_id and status_id not in seen_ids:
                    statuses.append(status)
                    seen_ids.add(status_id)
            if len(statuses) == before:
                break
            page += 1
            if max_page is not None and page > max_page:
                break

        items: list[ContentItem] = []
        segments: list[Segment] = []
        for index, status in enumerate(statuses[: request.max_items], start=1):
            item, segment = self._status_to_item(
                opener=opener,
                headers=headers,
                profile=profile,
                status=status,
                index=index,
                deep=request.deep,
            )
            items.append(item)
            if segment:
                segments.append(segment)

        if not items:
            raise ConnectorError(f"no xueqiu posts collected for {user_id}")
        diagnostics.append(f"items={len(items)}")
        if len(items) < (total or request.max_items):
            diagnostics.append("login_required_for_more_pages")
        return CollectResult(
            profile=profile,
            items=items,
            segments=segments,
            diagnostics=diagnostics,
        )

    def _status_to_item(
        self,
        opener: urllib.request.OpenerDirector,
        headers: dict[str, str],
        profile: Profile,
        status: dict[str, Any],
        index: int,
        deep: bool,
    ) -> tuple[ContentItem, Segment | None]:
        status_id = str(status.get("id") or status.get("status_id") or index)
        target = str(status.get("target") or f"/{profile.handle}/{status_id}")
        source_url = urllib.parse.urljoin(ROOT_URL, target)
        raw_html = str(status.get("description") or status.get("text") or "")
        detail_text = ""
        detail_raw: dict[str, Any] = {}
        if deep:
            detail_text, detail_raw = _fetch_detail_text(opener, headers, source_url)
        text = detail_text or _status_text(status)
        title = str(status.get("title") or "").strip()
        if not title:
            title = truncate(text, 72) or f"雪球动态 {status_id}"
        user = status.get("user") if isinstance(status.get("user"), dict) else {}
        item_id = stable_id("xueqiu", profile.id, status_id)
        item = ContentItem(
            id=item_id,
            profile_id=profile.id,
            platform="xueqiu",
            source_id=status_id,
            url=source_url,
            title=title,
            author=str(user.get("screen_name") or profile.display_name or ""),
            published_at=_created_at(status.get("created_at")),
            text=text,
            metrics={
                "retweet_count": _as_int(status.get("retweet_count")),
                "fav_count": _as_int(status.get("fav_count")),
                "reply_count": _as_int(status.get("reply_count") or status.get("comment_count")),
                "type": status.get("type"),
            },
            raw={
                "api": status,
                "html_description": raw_html,
                "detail": detail_raw,
            },
        )
        segment = None
        if item.text:
            segment = Segment(
                id=stable_id(item_id, "xueqiu", "text"),
                item_id=item_id,
                source="xueqiu:text",
                position=str(index),
                text=item.text,
                metadata={"source_id": status_id, "url": source_url},
            )
        return item, segment


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def _headers(referer: str, cookie: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json,text/plain,*/*",
        "Referer": referer,
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _read_text(
    opener: urllib.request.OpenerDirector,
    url: str,
    headers: dict[str, str],
    timeout: int = 30,
) -> str:
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_timeline(
    opener: urllib.request.OpenerDirector,
    headers: dict[str, str],
    user_id: str,
    type_id: str,
    page: int,
) -> dict[str, Any]:
    params = {"user_id": user_id, "type": type_id}
    if page > 1:
        params["page"] = str(page)
    url = f"{ROOT_URL}/v4/statuses/user_timeline.json?{urllib.parse.urlencode(params)}"
    try:
        return json.loads(_read_text(opener, url, headers))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "10022" in body:
            raise ConnectorError("xueqiu_login_required_for_more_pages") from exc
        raise ConnectorError(f"xueqiu timeline HTTP {exc.code}: {truncate(body, 180)}") from exc
    except json.JSONDecodeError as exc:
        raise ConnectorError("xueqiu timeline did not return JSON") from exc


def _fetch_detail_text(
    opener: urllib.request.OpenerDirector,
    headers: dict[str, str],
    url: str,
) -> tuple[str, dict[str, Any]]:
    try:
        html = _read_text(opener, url, headers)
    except Exception as exc:
        return "", {"error": f"{type(exc).__name__}: {exc}"}
    snowman_text = _snowman_status_text(html)
    article_text = _article_text(html)
    text = snowman_text or article_text
    return text, {"html_length": len(html), "used": "snowman" if snowman_text else "article"}


def _snowman_status_text(html: str) -> str:
    match = re.search(r"SNOWMAN_STATUS\s*=\s*(\{.*?\});", html or "", re.S)
    if not match:
        return ""
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ""
    return _clean_html_text(str(data.get("text") or data.get("description") or ""))


def _article_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        node = soup.select_one(".article__bd") or soup.select_one(".status-content")
        return html_to_text(str(node)) if node else ""
    except Exception:
        return ""


def _status_text(status: dict[str, Any]) -> str:
    text = _clean_html_text(str(status.get("text") or status.get("description") or ""))
    retweeted = status.get("retweeted_status")
    if isinstance(retweeted, dict):
        user = retweeted.get("user") if isinstance(retweeted.get("user"), dict) else {}
        name = user.get("screen_name") or ""
        retweeted_text = _clean_html_text(
            str(retweeted.get("text") or retweeted.get("description") or "")
        )
        if retweeted_text:
            text = normalize_text(f"{text}\n\n> {name}: {retweeted_text}")
    return text


def _clean_html_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    return html_to_text(value)


def _profile_meta(html: str, user_id: str) -> dict[str, str]:
    match = re.search(r"SNOWMAN_USER\s*=\s*(\{.*?\});", html or "", re.S)
    if match:
        try:
            data = json.loads(match.group(1))
            return {
                "screen_name": str(data.get("screen_name") or user_id),
                "description": str(data.get("description") or ""),
            }
        except json.JSONDecodeError:
            pass
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    title = _clean_html_text(title_match.group(1)) if title_match else user_id
    return {"screen_name": title.replace("的雪球", "").strip() or user_id, "description": ""}


def _user_id_from_source(source: str) -> str:
    match = re.search(r"xueqiu\.com/(?:u|P)/(\d+)", source, re.I)
    if match:
        return match.group(1)
    match = re.search(r"(\d{5,})", source)
    if match:
        return match.group(1)
    raise ConnectorError(f"cannot parse xueqiu user id from source: {source}")


def _type_from_source(source: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(source).query)
    value = (query.get("type") or ["10"])[0]
    return value if value in {"0", "2", "4", "9", "10", "11"} else "10"


def _created_at(value: Any) -> str | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    if numeric > 10_000_000_000:
        numeric = numeric // 1000
    return datetime.fromtimestamp(numeric, UTC).isoformat(timespec="seconds")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
