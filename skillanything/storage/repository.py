"""SQLite-backed repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from skillanything.models import (
    Comment,
    ContentItem,
    DistilledSkill,
    MediaAsset,
    Profile,
    ProfileBundle,
    Segment,
)
from skillanything.utils import from_json, to_json, utc_now


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    handle TEXT,
                    display_name TEXT,
                    description TEXT,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS content_items (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    source_id TEXT,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    author TEXT,
                    published_at TEXT,
                    text TEXT NOT NULL DEFAULT '',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_content_items_profile
                    ON content_items(profile_id, published_at);

                CREATE TABLE IF NOT EXISTS media_assets (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    url TEXT,
                    local_path TEXT,
                    mime_type TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    position TEXT NOT NULL,
                    text TEXT NOT NULL,
                    start_seconds REAL,
                    end_seconds REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
                    author TEXT,
                    text TEXT NOT NULL,
                    published_at TEXT,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    raw_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    version TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    skill_json TEXT NOT NULL,
                    output_dir TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 100,
                    request_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS search_documents (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    item_id TEXT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_search_documents_profile
                    ON search_documents(profile_id, kind);

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts
                    USING fts5(
                        doc_id UNINDEXED,
                        profile_id UNINDEXED,
                        item_id UNINDEXED,
                        kind UNINDEXED,
                        source_url UNINDEXED,
                        title,
                        body
                    )
                    """
                )
            except sqlite3.OperationalError:
                # Some Python builds omit FTS5. LIKE fallback still keeps Q&A usable.
                pass

    def upsert_profile(self, profile: Profile) -> Profile:
        now = utc_now()
        profile.created_at = profile.created_at or now
        profile.updated_at = now
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles (
                    id, platform, profile_url, handle, display_name, description,
                    raw_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    platform=excluded.platform,
                    profile_url=excluded.profile_url,
                    handle=excluded.handle,
                    display_name=excluded.display_name,
                    description=excluded.description,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                (
                    profile.id,
                    profile.platform,
                    profile.profile_url,
                    profile.handle,
                    profile.display_name,
                    profile.description,
                    to_json(profile.raw),
                    profile.created_at,
                    profile.updated_at,
                ),
            )
        return profile

    def upsert_items(self, items: Iterable[ContentItem]) -> int:
        count = 0
        now = utc_now()
        with self.connect() as conn:
            for item in items:
                item.created_at = item.created_at or now
                item.updated_at = now
                conn.execute(
                    """
                    INSERT INTO content_items (
                        id, profile_id, platform, source_id, url, title, author,
                        published_at, text, metrics_json, raw_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        author=excluded.author,
                        published_at=excluded.published_at,
                        text=excluded.text,
                        metrics_json=excluded.metrics_json,
                        raw_json=excluded.raw_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        item.id,
                        item.profile_id,
                        item.platform,
                        item.source_id,
                        item.url,
                        item.title,
                        item.author,
                        item.published_at,
                        item.text,
                        to_json(item.metrics),
                        to_json(item.raw),
                        item.created_at,
                        item.updated_at,
                    ),
                )
                count += 1
        return count

    def upsert_assets(self, assets: Iterable[MediaAsset]) -> int:
        count = 0
        with self.connect() as conn:
            for asset in assets:
                conn.execute(
                    """
                    INSERT INTO media_assets (
                        id, item_id, kind, url, local_path, mime_type, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind,
                        url=excluded.url,
                        local_path=excluded.local_path,
                        mime_type=excluded.mime_type,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        asset.id,
                        asset.item_id,
                        asset.kind,
                        asset.url,
                        asset.local_path,
                        asset.mime_type,
                        to_json(asset.metadata),
                    ),
                )
                count += 1
        return count

    def list_assets(
        self,
        profile_id: str | None = None,
        item_id: str | None = None,
        limit: int | None = None,
    ) -> list[MediaAsset]:
        query = """
            SELECT media_assets.* FROM media_assets
            JOIN content_items ON content_items.id = media_assets.item_id
        """
        params: list[object] = []
        where: list[str] = []
        if profile_id:
            where.append("content_items.profile_id = ?")
            params.append(profile_id)
        if item_id:
            where.append("media_assets.item_id = ?")
            params.append(item_id)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY media_assets.kind, media_assets.id"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def list_segments(
        self,
        profile_id: str | None = None,
        item_id: str | None = None,
    ) -> list[Segment]:
        query = """
            SELECT segments.* FROM segments
            JOIN content_items ON content_items.id = segments.item_id
        """
        params: list[object] = []
        where: list[str] = []
        if profile_id:
            where.append("content_items.profile_id = ?")
            params.append(profile_id)
        if item_id:
            where.append("segments.item_id = ?")
            params.append(item_id)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY segments.item_id, segments.source, segments.position"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._segment_from_row(row) for row in rows]

    def find_item(
        self,
        profile_id: str,
        item_id: str | None = None,
        source_id: str | None = None,
    ) -> ContentItem | None:
        if not item_id and not source_id:
            return None
        where = ["profile_id = ?"]
        params: list[object] = [profile_id]
        if item_id:
            where.append("id = ?")
            params.append(item_id)
        if source_id:
            where.append("source_id = ?")
            params.append(source_id)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM content_items WHERE " + " AND ".join(where) + " LIMIT 1",
                params,
            ).fetchone()
        return self._item_from_row(row) if row else None

    def update_asset_local_path(
        self,
        asset_id: str,
        local_path: str,
        mime_type: str | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE media_assets SET local_path = ?, mime_type = ? WHERE id = ?",
                (local_path, mime_type, asset_id),
            )

    def delete_multimodal_segments_for_assets(self, asset_ids: Iterable[str]) -> int:
        asset_ids = list(asset_ids)
        if not asset_ids:
            return 0
        placeholders = ",".join("?" for _ in asset_ids)
        sources = (
            "vision:openai_compatible",
            "vision:video_frame",
            "asr:qwen3_asr_flash",
            "multimodal:error",
            "vision:pending",
            "video:pending",
        )
        source_placeholders = ",".join("?" for _ in sources)
        with self.connect() as conn:
            cursor = conn.execute(
                f"""
                DELETE FROM segments
                WHERE source IN ({source_placeholders})
                  AND json_extract(metadata_json, '$.asset_id') IN ({placeholders})
                """,
                [*sources, *asset_ids],
            )
            return cursor.rowcount

    def upsert_segments(self, segments: Iterable[Segment]) -> int:
        count = 0
        with self.connect() as conn:
            for segment in segments:
                conn.execute(
                    """
                    INSERT INTO segments (
                        id, item_id, source, position, text, start_seconds,
                        end_seconds, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        source=excluded.source,
                        position=excluded.position,
                        text=excluded.text,
                        start_seconds=excluded.start_seconds,
                        end_seconds=excluded.end_seconds,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        segment.id,
                        segment.item_id,
                        segment.source,
                        segment.position,
                        segment.text,
                        segment.start_seconds,
                        segment.end_seconds,
                        to_json(segment.metadata),
                    ),
                )
                count += 1
        return count

    def upsert_comments(self, comments: Iterable[Comment]) -> int:
        count = 0
        with self.connect() as conn:
            for comment in comments:
                conn.execute(
                    """
                    INSERT INTO comments (
                        id, item_id, author, text, published_at, metrics_json, raw_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        author=excluded.author,
                        text=excluded.text,
                        published_at=excluded.published_at,
                        metrics_json=excluded.metrics_json,
                        raw_json=excluded.raw_json
                    """,
                    (
                        comment.id,
                        comment.item_id,
                        comment.author,
                        comment.text,
                        comment.published_at,
                        to_json(comment.metrics),
                        to_json(comment.raw),
                    ),
                )
                count += 1
        return count

    def list_profiles(self) -> list[Profile]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM profiles ORDER BY updated_at DESC").fetchall()
        return [self._profile_from_row(row) for row in rows]

    def get_profile(self, profile_id: str) -> Profile | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        return self._profile_from_row(row) if row else None

    def list_items(self, profile_id: str, limit: int = 200) -> list[ContentItem]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM content_items
                WHERE profile_id = ?
                ORDER BY COALESCE(published_at, created_at) DESC
                LIMIT ?
                """,
                (profile_id, limit),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def list_items_by_ids(self, profile_id: str, item_ids: list[str]) -> list[ContentItem]:
        if not item_ids:
            return []
        placeholders = ",".join("?" for _ in item_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM content_items
                WHERE profile_id = ? AND id IN ({placeholders})
                """,
                [profile_id, *item_ids],
            ).fetchall()
        by_id = {row["id"]: self._item_from_row(row) for row in rows}
        return [by_id[item_id] for item_id in item_ids if item_id in by_id]

    def load_bundle(self, profile_id: str, item_limit: int = 200) -> ProfileBundle:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise KeyError(f"profile not found: {profile_id}")
        items = self.list_items(profile_id, item_limit)
        item_ids = [item.id for item in items]
        if not item_ids:
            return ProfileBundle(profile=profile)
        placeholders = ",".join("?" for _ in item_ids)
        with self.connect() as conn:
            assets = [
                self._asset_from_row(row)
                for row in conn.execute(
                    f"SELECT * FROM media_assets WHERE item_id IN ({placeholders})", item_ids
                )
            ]
            segments = [
                self._segment_from_row(row)
                for row in conn.execute(
                    f"SELECT * FROM segments WHERE item_id IN ({placeholders})", item_ids
                )
            ]
            comments = [
                self._comment_from_row(row)
                for row in conn.execute(
                    f"SELECT * FROM comments WHERE item_id IN ({placeholders})", item_ids
                )
            ]
        return ProfileBundle(
            profile=profile,
            items=items,
            assets=assets,
            segments=segments,
            comments=comments,
        )

    def save_skill(self, skill: DistilledSkill, output_dir: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO skills (
                    id, profile_id, title, version, summary, skill_json, output_dir, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    version=excluded.version,
                    summary=excluded.summary,
                    skill_json=excluded.skill_json,
                    output_dir=excluded.output_dir
                """,
                (
                    skill.id,
                    skill.profile_id,
                    skill.title,
                    skill.version,
                    skill.summary,
                    to_json(skill.to_dict()),
                    output_dir,
                    utc_now(),
                ),
            )

    def create_job(self, job_id: str, job_type: str, request: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, type, status, progress, total, request_json, result_json,
                    created_at, updated_at
                )
                VALUES (?, ?, 'queued', 0, 100, ?, '{}', ?, ?)
                """,
                (job_id, job_type, to_json(request), now, now),
            )
        return self.get_job(job_id) or {}

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        current = self.get_job(job_id)
        if not current:
            return
        now = utc_now()
        values = {
            "status": status if status is not None else current["status"],
            "progress": progress if progress is not None else current["progress"],
            "total": total if total is not None else current["total"],
            "result_json": to_json(result) if result is not None else to_json(current["result"]),
            "error": error if error is not None else current.get("error"),
            "updated_at": now,
            "started_at": now if started else current.get("started_at"),
            "finished_at": now if finished else current.get("finished_at"),
        }
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, progress = ?, total = ?, result_json = ?, error = ?,
                    updated_at = ?, started_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    values["status"],
                    values["progress"],
                    values["total"],
                    values["result_json"],
                    values["error"],
                    values["updated_at"],
                    values["started_at"],
                    values["finished_at"],
                    job_id,
                ),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def get_app_settings(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def save_app_settings(self, values: dict[str, str]) -> dict[str, str]:
        now = utc_now()
        allowed = {
            "SKILLANYTHING_LLM_BASE_URL",
            "SKILLANYTHING_LLM_API_KEY",
            "SKILLANYTHING_LLM_MODEL",
            "SKILLANYTHING_VISION_BASE_URL",
            "SKILLANYTHING_VISION_API_KEY",
            "SKILLANYTHING_VISION_MODEL",
            "SKILLANYTHING_ASR_BASE_URL",
            "SKILLANYTHING_ASR_API_KEY",
            "SKILLANYTHING_ASR_MODEL",
            "SKILLANYTHING_ASR_LANGUAGE",
            "SKILLANYTHING_XUEQIU_COOKIE",
            "SKILLANYTHING_CDP_URL",
            "SKILLANYTHING_MEDIA_MAX_ASSETS",
        }
        clean = {key: str(value) for key, value in values.items() if key in allowed}
        with self.connect() as conn:
            for key, value in clean.items():
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        updated_at=excluded.updated_at
                    """,
                    (key, value, now),
                )
        return self.get_app_settings()

    def count_search_documents(self, profile_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM search_documents WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def rebuild_search_index(self, profile_id: str) -> int:
        bundle = self.load_bundle(profile_id, item_limit=5000)
        docs: list[dict[str, Any]] = []
        segments_by_item: dict[str, list[Segment]] = {}
        for segment in bundle.segments:
            segments_by_item.setdefault(segment.item_id, []).append(segment)

        for item in bundle.items:
            docs.append(
                {
                    "id": f"item:{item.id}",
                    "profile_id": profile_id,
                    "item_id": item.id,
                    "kind": "post",
                    "title": item.title,
                    "body": item.text,
                    "source_url": item.url,
                    "metadata": {"source_id": item.source_id, "published_at": item.published_at},
                }
            )
            for segment in segments_by_item.get(item.id, []):
                docs.append(
                    {
                        "id": f"segment:{segment.id}",
                        "profile_id": profile_id,
                        "item_id": item.id,
                        "kind": segment.source,
                        "title": item.title,
                        "body": segment.text,
                        "source_url": item.url,
                        "metadata": {
                            "position": segment.position,
                            "segment_id": segment.id,
                            **segment.metadata,
                        },
                    }
                )

        for skill in self._skills_for_profile(profile_id):
            docs.append(
                {
                    "id": f"skill:{skill['id']}",
                    "profile_id": profile_id,
                    "item_id": None,
                    "kind": "skill",
                    "title": skill["title"],
                    "body": skill["summary"],
                    "source_url": skill.get("output_dir") or "",
                    "metadata": {"skill_id": skill["id"]},
                }
            )
            data = self.get_skill_json(skill["id"]) or {}
            reports = data.get("metadata", {}).get("research_reports", [])
            if isinstance(reports, list):
                for index, report in enumerate(reports):
                    if not isinstance(report, dict):
                        continue
                    body = "\n".join(
                        str(report.get(key) or "")
                        for key in [
                            "question",
                            "indicators",
                            "tools",
                            "transmission_chain",
                            "conclusion",
                        ]
                    )
                    docs.append(
                        {
                            "id": f"report:{skill['id']}:{index}",
                            "profile_id": profile_id,
                            "item_id": None,
                            "kind": "analysis",
                            "title": str(report.get("title") or skill["title"]),
                            "body": body,
                            "source_url": str(report.get("source_url") or ""),
                            "metadata": {"skill_id": skill["id"], "report_index": index},
                        }
                    )

        now = utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM search_documents WHERE profile_id = ?", (profile_id,))
            try:
                conn.execute("DELETE FROM search_documents_fts WHERE profile_id = ?", (profile_id,))
                has_fts = True
            except sqlite3.OperationalError:
                has_fts = False
            for doc in docs:
                conn.execute(
                    """
                    INSERT INTO search_documents (
                        id, profile_id, item_id, kind, title, body, source_url,
                        metadata_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc["id"],
                        doc["profile_id"],
                        doc["item_id"],
                        doc["kind"],
                        doc["title"],
                        doc["body"],
                        doc["source_url"],
                        to_json(doc["metadata"]),
                        now,
                    ),
                )
                if has_fts:
                    conn.execute(
                        """
                        INSERT INTO search_documents_fts (
                            doc_id, profile_id, item_id, kind, source_url, title, body
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc["id"],
                            doc["profile_id"],
                            doc["item_id"],
                            doc["kind"],
                            doc["source_url"],
                            doc["title"],
                            doc["body"],
                        ),
                    )
        return len(docs)

    def search_documents(
        self,
        profile_id: str,
        query: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        fts_query = _fts_query(query)
        rows: list[sqlite3.Row] = []
        with self.connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT doc_id AS id, profile_id, item_id, kind, title, body, source_url
                    FROM search_documents_fts
                    WHERE profile_id = ? AND search_documents_fts MATCH ?
                    ORDER BY bm25(search_documents_fts)
                    LIMIT ?
                    """,
                    (profile_id, fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if len(rows) < limit:
                like = f"%{query}%"
                rows.extend(
                    conn.execute(
                    """
                    SELECT id, profile_id, item_id, kind, title, body, source_url
                    FROM search_documents
                    WHERE profile_id = ? AND (title LIKE ? OR body LIKE ?)
                    ORDER BY
                        CASE WHEN title LIKE ? THEN 0 ELSE 1 END,
                        length(body) DESC
                    LIMIT ?
                    """,
                    (profile_id, like, like, like, limit),
                    ).fetchall()
                )
            if len(rows) < limit:
                tokens = re_tokens(query)
                for token in tokens[:40]:
                    like = f"%{token}%"
                    token_rows = conn.execute(
                        """
                        SELECT id, profile_id, item_id, kind, title, body, source_url
                        FROM search_documents
                        WHERE profile_id = ? AND (title LIKE ? OR body LIKE ?)
                        LIMIT ?
                        """,
                        (profile_id, like, like, limit),
                    ).fetchall()
                    rows.extend(token_rows)
                    if len(rows) >= limit:
                        break
        seen: set[str] = set()
        docs: list[dict[str, Any]] = []
        for row in rows:
            doc = dict(row)
            if doc["id"] in seen:
                continue
            seen.add(doc["id"])
            doc["body"] = doc.get("body") or ""
            docs.append(doc)
            if len(docs) >= limit:
                break
        return docs

    def _skills_for_profile(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, profile_id, title, version, summary, output_dir, created_at
                FROM skills
                WHERE profile_id = ?
                ORDER BY created_at DESC
                """,
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_skill_json(self, skill_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT skill_json FROM skills WHERE id = ?", (skill_id,)).fetchone()
        return from_json(row["skill_json"], None) if row else None

    def save_skill_json_output(self, skill_id: str, output_dir: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE skills SET output_dir = ? WHERE id = ?",
                (output_dir, skill_id),
            )

    def list_skills(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, profile_id, title, version, summary, output_dir, created_at "
                "FROM skills "
                "ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> Profile:
        return Profile(
            id=row["id"],
            platform=row["platform"],
            profile_url=row["profile_url"],
            handle=row["handle"],
            display_name=row["display_name"],
            description=row["description"],
            raw=from_json(row["raw_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> ContentItem:
        return ContentItem(
            id=row["id"],
            profile_id=row["profile_id"],
            platform=row["platform"],
            source_id=row["source_id"],
            url=row["url"],
            title=row["title"],
            author=row["author"],
            published_at=row["published_at"],
            text=row["text"],
            metrics=from_json(row["metrics_json"], {}),
            raw=from_json(row["raw_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> MediaAsset:
        return MediaAsset(
            id=row["id"],
            item_id=row["item_id"],
            kind=row["kind"],
            url=row["url"],
            local_path=row["local_path"],
            mime_type=row["mime_type"],
            metadata=from_json(row["metadata_json"], {}),
        )

    @staticmethod
    def _segment_from_row(row: sqlite3.Row) -> Segment:
        return Segment(
            id=row["id"],
            item_id=row["item_id"],
            source=row["source"],
            position=row["position"],
            text=row["text"],
            start_seconds=row["start_seconds"],
            end_seconds=row["end_seconds"],
            metadata=from_json(row["metadata_json"], {}),
        )

    @staticmethod
    def _comment_from_row(row: sqlite3.Row) -> Comment:
        return Comment(
            id=row["id"],
            item_id=row["item_id"],
            author=row["author"],
            text=row["text"],
            published_at=row["published_at"],
            metrics=from_json(row["metrics_json"], {}),
            raw=from_json(row["raw_json"], {}),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "status": row["status"],
            "progress": row["progress"],
            "total": row["total"],
            "request": from_json(row["request_json"], {}),
            "result": from_json(row["result_json"], {}),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }


def _fts_query(query: str) -> str:
    tokens = re_tokens(query)
    if not tokens:
        return query.replace('"', " ")
    return " OR ".join(f'"{token}"' for token in tokens[:12])


def re_tokens(query: str) -> list[str]:
    import re

    raw_tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_.:-]{2,}", query or "")
    tokens: list[str] = []
    for token in raw_tokens:
        if token not in tokens:
            tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]{5,}", token):
            for width in (4, 3, 2):
                for index in range(0, len(token) - width + 1):
                    piece = token[index : index + width]
                    if piece not in tokens:
                        tokens.append(piece)
    return tokens
