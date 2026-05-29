"""Content-addressed local archive for raw evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

from skillanything.utils import ensure_dir


class Archive:
    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)

    def write_bytes(self, namespace: str, name_hint: str, data: bytes) -> Path:
        digest = hashlib.sha256(data).hexdigest()
        suffix = Path(name_hint).suffix or ".bin"
        directory = ensure_dir(self.root / namespace / digest[:2])
        path = directory / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        return path

    def write_text(self, namespace: str, name_hint: str, text: str) -> Path:
        return self.write_bytes(namespace, name_hint, text.encode("utf-8"))
