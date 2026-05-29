"""Small HTTP helpers built on the standard library."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)


def fetch_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    merged = {"User-Agent": DEFAULT_UA, **(headers or {})}
    req = urllib.request.Request(url, headers=merged)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    data = fetch_bytes(url, headers=headers, timeout=timeout)
    return data.decode("utf-8", errors="replace")


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    return json.loads(fetch_text(url, headers=headers, timeout=timeout))
