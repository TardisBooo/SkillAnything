"""Small shared utilities."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def epoch_ms() -> int:
    return int(time.time() * 1000)


def stable_id(*parts: Any) -> str:
    raw = "\n".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def slugify(value: str, fallback: str = "skill") -> str:
    normalized = unicodedata.normalize("NFKD", value).strip().lower()
    normalized = re.sub(r"[^\w\s.-]+", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[\s_.]+", "-", normalized).strip("-")
    return normalized or fallback


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def from_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def truncate(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"
