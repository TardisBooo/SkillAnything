"""Xiaohongshu profile connector.

The connector intentionally uses only public page state and optional local browser rendering. It
does not bypass login, CAPTCHA, paid content, or platform access controls.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlparse

from skillanything.config import Settings
from skillanything.connectors.base import Connector, ConnectorError, FetchRequest
from skillanything.connectors.http import fetch_text
from skillanything.extract.text import extract_image_urls, html_title, html_to_text
from skillanything.models import CollectResult, ContentItem, MediaAsset, Profile, Segment
from skillanything.utils import stable_id, truncate


class XiaohongshuConnector(Connector):
    name = "xiaohongshu"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def can_handle(self, request: FetchRequest) -> bool:
        host = urlparse(request.source).netloc.lower()
        return request.platform in {"xiaohongshu", "xhs", "redbook"} or "xiaohongshu.com" in host

    def collect(self, request: FetchRequest) -> CollectResult:
        raw_html = self._fetch_html(request.source)
        state = self._parse_initial_state(raw_html)
        if not state:
            raw_html = self._render_html(request.source)
            state = self._parse_initial_state(raw_html)
        if not state:
            return self._fallback_webpage(request, raw_html)

        detail_notes = self._detail_notes_from_state(state)
        if self._is_note_url(request.source) and detail_notes:
            return self._collect_detail_notes(request, detail_notes)

        profile = self._profile_from_state(request.source, state)
        items: list[ContentItem] = []
        assets: list[MediaAsset] = []
        segments: list[Segment] = []

        cards = self._note_cards(state)
        browser_cards = (
            self._browser_profile_cards(request.source, request.max_items)
            if request.deep and self.settings
            else []
        )
        if browser_cards:
            cards = browser_cards

        for index, card in enumerate(cards[: request.max_items], start=1):
            title = (
                _first_text(card, "displayTitle", "display_title", "title")
                or f"XHS note {index}"
            )
            note_id = self._note_id(card) or stable_id(profile.id, index, title)
            token = card.get("xsecToken") or card.get("xsec_token")
            source_url = self._note_url(note_id, token)
            detail = self._fetch_detail_note(source_url) if request.deep else None
            note = detail or card
            user = card.get("user") if isinstance(card.get("user"), dict) else {}
            interact = self._interact_info(note) or self._interact_info(card)
            kind = note.get("type") or card.get("type") or "normal"
            title = _first_text(note, "title", "displayTitle", "display_title") or title
            text = self._note_text(note, title)
            item_id = stable_id("xiaohongshu", profile.id, note_id, title)
            item = ContentItem(
                id=item_id,
                profile_id=profile.id,
                platform="xiaohongshu",
                source_id=str(note_id),
                url=source_url,
                title=title,
                author=(
                    user.get("nickname")
                    or user.get("nickName")
                    or user.get("nick_name")
                    or profile.display_name
                ),
                text=text,
                metrics=self._metrics(interact),
                raw={"card": card, "detail": detail} if detail else card,
            )
            items.append(item)
            segments.append(
                Segment(
                    id=stable_id(item_id, "xhs-card", index),
                    item_id=item_id,
                    source="xiaohongshu:detail" if detail else "xiaohongshu:ssr_card",
                    position=str(index),
                    text=text,
                    metadata={"kind": kind, "note_id": note_id, "url": source_url},
                )
            )
            segments.extend(self._subtitle_segments(note, item_id))
            if request.include_media:
                image_urls = self._note_images(note) or self._card_images(card)
                for image_index, image_url in enumerate(image_urls, start=1):
                    assets.append(
                        MediaAsset(
                            id=stable_id(item_id, "image", image_url),
                            item_id=item_id,
                            kind="image",
                            url=image_url,
                            metadata={"position": image_index, "source": "detail_image"},
                        )
                    )
                assets.extend(self._video_assets(note, item_id))
                assets.extend(self._subtitle_assets(note, item_id))

        return CollectResult(
            profile=profile,
            items=items,
            assets=assets,
            segments=segments,
            diagnostics=[
                "source=xiaohongshu_initial_state",
                f"deep={request.deep}",
                f"items={len(items)}",
                f"assets={len(assets)}",
                f"browser_cards={len(browser_cards)}",
            ],
        )

    @staticmethod
    def _fetch_html(url: str) -> str:
        return fetch_text(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.xiaohongshu.com/",
            },
            timeout=30,
        )

    @staticmethod
    def _render_html(url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise ConnectorError("Playwright is required for browser-rendered capture") from exc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
                locale="zh-CN",
            )
            page.goto(url, wait_until="networkidle", timeout=45000)
            html_text = page.content()
            browser.close()
            return html_text

    def _browser_profile_cards(self, source: str, max_items: int) -> list[dict]:
        if self._is_note_url(source):
            return []
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return []

        cards: list[dict] = []
        seen_card_keys: set[str] = set()
        with sync_playwright() as p:
            browser = None
            try:
                if self.settings and self.settings.cdp_url:
                    browser = p.chromium.connect_over_cdp(self.settings.cdp_url, timeout=2500)
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                else:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir="",
                        headless=True,
                        locale="zh-CN",
                    )
                page = context.new_page()
            except Exception:
                try:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(locale="zh-CN")
                except Exception:
                    return []

            def append_card(card: dict) -> None:
                note_id = self._note_id(card)
                title = (
                    card.get("title")
                    or card.get("displayTitle")
                    or card.get("display_title")
                    or ""
                )
                token = card.get("xsecToken") or card.get("xsec_token")
                key = note_id or stable_id(title, token)
                if key in seen_card_keys:
                    return
                seen_card_keys.add(key)
                cards.append(card)

            def on_response(response) -> None:
                if "api/sns/web/v1/user_posted" not in response.url:
                    return
                try:
                    payload = json.loads(response.text())
                except Exception:
                    return
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                notes = data.get("notes") if isinstance(data.get("notes"), list) else []
                for note in notes:
                    if not isinstance(note, dict):
                        continue
                    card = (
                        note.get("noteCard")
                        or note.get("note_card")
                        or note
                    )
                    if isinstance(card, dict):
                        append_card(card)

            def collect_dom_cards() -> None:
                try:
                    dom_cards = page.eval_on_selector_all(
                        ".note-item",
                        """(els) => els.map((el) => {
                            const hidden = el.querySelector('a[href^="/explore/"]');
                            const detail =
                                el.querySelector('a.cover[href*="/user/profile/"]') ||
                                el.querySelector('a.title[href*="/user/profile/"]');
                            const rawHref =
                                detail?.getAttribute("href") ||
                                hidden?.getAttribute("href") ||
                                "";
                            const href = new URL(rawHref, location.origin);
                            const noteMatch =
                                href.pathname.match(/\\/explore\\/([^/?#]+)/) ||
                                href.pathname.match(/\\/user\\/profile\\/[^/]+\\/([^/?#]+)/);
                            const noteId = noteMatch ? noteMatch[1] : "";
                            const image = el.querySelector("img")?.src || "";
                            const title = el.querySelector(".title")?.innerText?.trim() || "";
                            const liked =
                                el.querySelector(".count")?.innerText?.trim() ||
                                el.querySelector(".like-wrapper")?.innerText?.trim() ||
                                "";
                            const token = href.searchParams.get("xsec_token") || "";
                            return {
                                noteId,
                                note_id: noteId,
                                xsecToken: token,
                                xsec_token: token,
                                displayTitle: title,
                                display_title: title,
                                type: el.querySelector(".play-icon") ? "video" : "normal",
                                cover: image ? {
                                    urlDefault: image,
                                    urlPre: image,
                                    url: image,
                                    infoList: [{ url: image }],
                                } : {},
                                interactInfo: liked ? { likedCount: liked } : {},
                            };
                        }).filter((card) => card.noteId)""",
                    )
                except Exception:
                    return
                for card in dom_cards:
                    if isinstance(card, dict):
                        append_card(card)

            page.on("response", on_response)
            try:
                page.goto(source, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                collect_dom_cards()
                page.locator("body").click(position={"x": 500, "y": 500}, timeout=3000)
                stable_rounds = 0
                last_count = 0
                while len(cards) < max_items and stable_rounds < 4:
                    page.mouse.wheel(0, 2600)
                    page.wait_for_timeout(1400)
                    collect_dom_cards()
                    if len(cards) == last_count:
                        stable_rounds += 1
                    else:
                        stable_rounds = 0
                        last_count = len(cards)
            except Exception:
                pass
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    if browser:
                        browser.close()
                    elif "context" in locals():
                        context.close()
                except Exception:
                    pass
        return cards

    @staticmethod
    def _parse_initial_state(raw_html: str) -> dict:
        match = re.search(r"<script>window\.__INITIAL_STATE__=(.*?)</script>", raw_html, re.S)
        if not match:
            return {}
        raw = html.unescape(match.group(1))
        raw = re.sub(r"(?<=[:,\[])undefined(?=[,}\]])", "null", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _is_note_url(source: str) -> bool:
        return "/explore/" in urlparse(source).path

    def _collect_detail_notes(self, request: FetchRequest, notes: list[dict]) -> CollectResult:
        first = notes[0]
        author = first.get("user") if isinstance(first.get("user"), dict) else {}
        profile = Profile(
            id=stable_id("xiaohongshu", author.get("userId") or request.source),
            platform="xiaohongshu",
            profile_url=request.source,
            handle=author.get("userId") or _profile_id_from_url(request.source),
            display_name=author.get("nickname") or author.get("nickName") or "Xiaohongshu note",
            description=None,
            raw={"source_kind": "single_note"},
        )
        items: list[ContentItem] = []
        assets: list[MediaAsset] = []
        segments: list[Segment] = []
        for index, note in enumerate(notes[: request.max_items], start=1):
            note_id = self._note_id(note) or stable_id(request.source, index)
            title = (
                _first_text(note, "title", "displayTitle", "display_title")
                or f"XHS note {index}"
            )
            token = note.get("xsecToken") or note.get("xsec_token")
            source_url = self._note_url(note_id, token)
            item_id = stable_id("xiaohongshu", profile.id, note_id, title)
            interact = self._interact_info(note)
            item = ContentItem(
                id=item_id,
                profile_id=profile.id,
                platform="xiaohongshu",
                source_id=str(note_id),
                url=source_url,
                title=title,
                author=profile.display_name,
                text=self._note_text(note, title),
                metrics=self._metrics(interact),
                raw=note,
            )
            items.append(item)
            segments.append(
                Segment(
                    id=stable_id(item_id, "xhs-detail", index),
                    item_id=item_id,
                    source="xiaohongshu:detail",
                    position=str(index),
                    text=item.text,
                    metadata={"note_id": note_id, "url": source_url},
                )
            )
            segments.extend(self._subtitle_segments(note, item_id))
            if request.include_media:
                for image_index, image_url in enumerate(self._note_images(note), start=1):
                    assets.append(
                        MediaAsset(
                            id=stable_id(item_id, "image", image_url),
                            item_id=item_id,
                            kind="image",
                            url=image_url,
                            metadata={"position": image_index, "source": "detail_image"},
                        )
                    )
                assets.extend(self._video_assets(note, item_id))
                assets.extend(self._subtitle_assets(note, item_id))
        return CollectResult(
            profile=profile,
            items=items,
            assets=assets,
            segments=segments,
            diagnostics=[
                "source=xiaohongshu_note_detail",
                f"items={len(items)}",
                f"assets={len(assets)}",
            ],
        )
    @staticmethod
    def _profile_from_state(source: str, state: dict) -> Profile:
        user_state = state.get("user") if isinstance(state.get("user"), dict) else {}
        page_data = user_state.get("userPageData")
        page_data = page_data if isinstance(page_data, dict) else {}
        basic = page_data.get("basicInfo") if isinstance(page_data.get("basicInfo"), dict) else {}
        user_id = (
            basic.get("redId")
            or _profile_id_from_url(source)
            or stable_id("xiaohongshu", source)
        )
        tags = page_data.get("tags") if isinstance(page_data.get("tags"), list) else []
        interactions = (
            page_data.get("interactions")
            if isinstance(page_data.get("interactions"), list)
            else []
        )
        return Profile(
            id=stable_id("xiaohongshu", source),
            platform="xiaohongshu",
            profile_url=source,
            handle=str(user_id),
            display_name=basic.get("nickname") or "Xiaohongshu user",
            description=basic.get("desc"),
            raw={
                "basicInfo": basic,
                "interactions": interactions,
                "tags": tags,
                "profile_id": _profile_id_from_url(source),
            },
        )

    @staticmethod
    def _note_cards(state: dict) -> list[dict]:
        user_state = state.get("user") if isinstance(state.get("user"), dict) else {}
        notes = user_state.get("notes") if isinstance(user_state.get("notes"), list) else []
        cards: list[dict] = []
        for column in notes:
            entries = column if isinstance(column, list) else [column]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                card = entry.get("noteCard") if isinstance(entry.get("noteCard"), dict) else entry
                if isinstance(card, dict):
                    cards.append(card)
        return cards

    @staticmethod
    def _detail_notes_from_state(state: dict) -> list[dict]:
        note_state = state.get("note") if isinstance(state.get("note"), dict) else {}
        detail_map = note_state.get("noteDetailMap")
        if not isinstance(detail_map, dict):
            return []
        notes: list[dict] = []
        for detail in detail_map.values():
            if isinstance(detail, dict) and isinstance(detail.get("note"), dict):
                notes.append(detail["note"])
        return notes

    def _fetch_detail_note(self, source_url: str) -> dict | None:
        try:
            raw_html = self._fetch_html(source_url)
            state = self._parse_initial_state(raw_html)
            notes = self._detail_notes_from_state(state)
            if notes:
                return notes[0]
        except Exception:
            return None
        return None

    @staticmethod
    def _note_text(card: dict, title: str) -> str:
        parts = [title]
        for key in ("desc", "description", "content", "displayTitle", "display_title"):
            value = card.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in parts:
                parts.append(value.strip())
        tags = card.get("tagList") or card.get("tag_list")
        tags = tags if isinstance(tags, list) else []
        tag_names = [tag.get("name") for tag in tags if isinstance(tag, dict) and tag.get("name")]
        if tag_names:
            parts.append("话题：" + "、".join(tag_names))
        interact = XiaohongshuConnector._interact_info(card)
        if interact:
            parts.append(
                "互动数据："
                f"点赞 {interact.get('likedCount', '未知')}，"
                f"收藏 {interact.get('collectedCount', '未知')}，"
                f"评论 {interact.get('commentCount', '未知')}，"
                f"分享 {interact.get('shareCount', '未知')}，"
                f"置顶 {bool(interact.get('sticky'))}"
            )
        return "\n".join(parts)

    @staticmethod
    def _interact_info(card: dict) -> dict:
        interact = card.get("interactInfo") or card.get("interact_info")
        return interact if isinstance(interact, dict) else {}

    @staticmethod
    def _metrics(interact: dict) -> dict:
        return {
            "liked_count": interact.get("likedCount") or interact.get("liked_count"),
            "collected_count": interact.get("collectedCount") or interact.get("collected_count"),
            "comment_count": interact.get("commentCount") or interact.get("comment_count"),
            "share_count": interact.get("shareCount") or interact.get("share_count"),
            "sticky": interact.get("sticky"),
        }

    @staticmethod
    def _note_id(card: dict) -> str | None:
        for key in ("noteId", "note_id", "id"):
            value = card.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _card_images(card: dict) -> list[str]:
        images: list[str] = []
        cover = card.get("cover") if isinstance(card.get("cover"), dict) else {}
        for key in ("urlDefault", "url_default", "urlPre", "url_pre", "url"):
            value = cover.get(key)
            if isinstance(value, str) and value and value not in images:
                images.append(value)
        info_list = cover.get("infoList") or cover.get("info_list")
        info_list = info_list if isinstance(info_list, list) else []
        for info in info_list:
            if isinstance(info, dict):
                value = info.get("url")
                if isinstance(value, str) and value and value not in images:
                    images.append(value)
        return images

    @staticmethod
    def _note_images(note: dict) -> list[str]:
        images: list[str] = []
        image_list = note.get("imageList") or note.get("image_list")
        image_list = image_list if isinstance(image_list, list) else []
        for image in image_list:
            if not isinstance(image, dict):
                continue
            for key in ("urlDefault", "url_default", "urlPre", "url_pre", "url"):
                value = image.get(key)
                if isinstance(value, str) and value and value not in images:
                    images.append(value)
            info_list = image.get("infoList") or image.get("info_list")
            info_list = info_list if isinstance(info_list, list) else []
            for info in info_list:
                value = info.get("url") if isinstance(info, dict) else None
                if isinstance(value, str) and value and value not in images:
                    images.append(value)
        return images

    @staticmethod
    def _video_assets(note: dict, item_id: str) -> list[MediaAsset]:
        urls = [
            url
            for url in _urls_from_video(note.get("video"))
            if ".mp4" in url.lower() or ".m3u8" in url.lower()
        ]
        assets: list[MediaAsset] = []
        best_urls = _best_video_urls(urls)
        for index, url in enumerate(best_urls, start=1):
            assets.append(
                MediaAsset(
                    id=stable_id(item_id, "video", url),
                    item_id=item_id,
                    kind="video",
                    url=url,
                    metadata={"position": index, "source": "xhs_video"},
                )
            )
        return assets

    @staticmethod
    def _subtitle_assets(note: dict, item_id: str) -> list[MediaAsset]:
        urls = [url for url in _urls_from_video(note.get("video")) if ".srt" in url.lower()]
        assets: list[MediaAsset] = []
        for index, url in enumerate(dict.fromkeys(urls), start=1):
            assets.append(
                MediaAsset(
                    id=stable_id(item_id, "subtitle", url),
                    item_id=item_id,
                    kind="subtitle",
                    url=url,
                    metadata={"position": index, "source": "xhs_subtitle"},
                )
            )
        return assets

    @staticmethod
    def _subtitle_segments(note: dict, item_id: str) -> list[Segment]:
        segments: list[Segment] = []
        urls = [url for url in _urls_from_video(note.get("video")) if ".srt" in url.lower()]
        for index, url in enumerate(dict.fromkeys(urls), start=1):
            try:
                raw = fetch_text(url, timeout=30)
            except Exception:
                continue
            text = _srt_to_text(raw)
            if not text:
                continue
            segments.append(
                Segment(
                    id=stable_id(item_id, "subtitle", url, text[:80]),
                    item_id=item_id,
                    source="xiaohongshu:subtitle",
                    position=f"subtitle:{index}",
                    text=text,
                    metadata={"url": url},
                )
            )
        return segments

    @staticmethod
    def _note_url(note_id: str, token: str | None) -> str:
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if token:
            return f"{url}?xsec_token={token}&xsec_source=pc_user"
        return url

    @staticmethod
    def _fallback_webpage(request: FetchRequest, raw_html: str) -> CollectResult:
        text = html_to_text(raw_html)
        title = html_title(raw_html) or "Xiaohongshu page"
        profile = Profile(
            id=stable_id("xiaohongshu", request.source),
            platform="xiaohongshu",
            profile_url=request.source,
            handle=_profile_id_from_url(request.source),
            display_name=title.replace(" - 小红书", ""),
            raw={"source": "web_fallback"},
        )
        item_id = stable_id("xiaohongshu", profile.id, "page")
        item = ContentItem(
            id=item_id,
            profile_id=profile.id,
            platform="xiaohongshu",
            source_id=request.source,
            url=request.source,
            title=title,
            text=truncate(text, 10000),
            raw={"html_length": len(raw_html)},
        )
        assets = [
            MediaAsset(
                id=stable_id(item_id, "image", image_url),
                item_id=item_id,
                kind="image",
                url=image_url,
            )
            for image_url in extract_image_urls(raw_html)
        ]
        segment = Segment(
            id=stable_id(item_id, "webpage", "body"),
            item_id=item_id,
            source="xiaohongshu:webpage",
            position="body",
            text=item.text,
        )
        return CollectResult(
            profile=profile,
            items=[item],
            assets=assets if request.include_media else [],
            segments=[segment],
            diagnostics=["source=xiaohongshu_web_fallback"],
        )


def _profile_id_from_url(source: str) -> str | None:
    match = re.search(r"/user/profile/([^/?#]+)", source)
    return match.group(1) if match else None


def _first_text(data: dict, *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _merge_cards(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    seen_titles: set[str] = set()
    for card in [*primary, *secondary]:
        note_id = XiaohongshuConnector._note_id(card)
        title = (
            card.get("title")
            or card.get("displayTitle")
            or card.get("display_title")
            or ""
        )
        token = card.get("xsecToken") or card.get("xsec_token")
        key = note_id or stable_id(title, token)
        title_key = str(title).strip()
        if key in seen or (not note_id and title_key and title_key in seen_titles):
            continue
        seen.add(key)
        if title_key:
            seen_titles.add(title_key)
        merged.append(card)
    return merged


def _best_video_urls(urls: list[str]) -> list[str]:
    unique = list(dict.fromkeys(urls))
    if not unique:
        return []
    unique.sort(key=lambda url: ("sns-bak" in url, "_258." not in url))
    return unique[:1]


def _urls_from_video(video: object) -> list[str]:
    if not isinstance(video, dict):
        return []
    expanded: dict = dict(video)
    media_v2 = video.get("mediaV2")
    if isinstance(media_v2, str):
        try:
            expanded["mediaV2Parsed"] = json.loads(media_v2)
        except json.JSONDecodeError:
            expanded["mediaV2Raw"] = media_v2
    raw = json.dumps(expanded, ensure_ascii=False)
    urls = re.findall(r"https?://[^\"'\\\s]+", raw)
    return [url.replace("\\u0026", "&").replace("\\/", "/") for url in urls]


def _srt_to_text(raw: str) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isdigit():
            continue
        if "-->" in stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines)
