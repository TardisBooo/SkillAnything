"""Text extraction utilities."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip = True
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip = False
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


def normalize_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(raw_html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_html or "", "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        return normalize_text(soup.get_text("\n"))
    except Exception:
        parser = _TextHTMLParser()
        parser.feed(raw_html or "")
        return parser.text()


def html_title(raw_html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html or "", re.I | re.S)
    if not match:
        return None
    return normalize_text(match.group(1))


def extract_image_urls(raw_html: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", raw_html or "", re.I):
        url = html.unescape(match.group(1)).strip()
        if url and url not in urls:
            urls.append(url)
    return urls
