"""Download and persist collected media assets locally."""

from __future__ import annotations

import mimetypes
import subprocess
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from skillanything.connectors.http import fetch_bytes
from skillanything.models import MediaAsset
from skillanything.storage.repository import Repository
from skillanything.utils import ensure_dir, stable_id


@dataclass(slots=True)
class ArchiveMediaResult:
    attempted: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "downloaded": self.downloaded,
            "skipped": self.skipped,
            "failed": self.failed,
            "failures": self.failures or [],
        }


class MediaArchiver:
    def __init__(self, repo: Repository, archive_root: Path) -> None:
        self.repo = repo
        self.archive_root = ensure_dir(archive_root)

    def archive_profile(
        self,
        profile_id: str,
        kinds: set[str] | None = None,
        limit: int | None = None,
        force: bool = False,
        workers: int = 12,
    ) -> ArchiveMediaResult:
        assets = self.repo.list_assets(profile_id, limit=limit)
        if kinds:
            assets = [asset for asset in assets if asset.kind in kinds]
        result = ArchiveMediaResult(attempted=len(assets), failures=[])

        def work(asset: MediaAsset) -> tuple[str, Path | None, str | None, str | None, bool]:
            if asset.local_path and Path(asset.local_path).exists() and not force:
                return asset.id, None, asset.mime_type, None, True
            if not asset.url:
                return asset.id, None, None, "missing url", False
            try:
                path, mime_type = self._download_asset(asset)
            except Exception as exc:
                return asset.id, None, None, f"{type(exc).__name__}: {exc}", False
            return asset.id, path, mime_type, None, False

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(work, asset) for asset in assets]
            for future in as_completed(futures):
                asset_id, path, mime_type, error, skipped = future.result()
                if skipped:
                    result.skipped += 1
                    continue
                if error:
                    result.failed += 1
                    if len(result.failures) < 50:
                        result.failures.append(f"{asset_id}: {error}")
                    continue
                if path is None:
                    result.failed += 1
                    if len(result.failures) < 50:
                        result.failures.append(f"{asset_id}: missing downloaded path")
                    continue
                self.repo.update_asset_local_path(asset_id, str(path), mime_type)
                result.downloaded += 1
        return result

    def _download_asset(self, asset: MediaAsset) -> tuple[Path, str | None]:
        assert asset.url is not None
        data = fetch_bytes(asset.url, timeout=120)
        if not data:
            raise urllib.error.URLError("empty response")
        mime_type = _guess_mime(asset.url, data)
        suffix = _suffix_for(asset.url, mime_type)
        directory = ensure_dir(self.archive_root / asset.kind / asset.id[:2])
        path = directory / f"{asset.id}-{stable_id(data)}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        return path, mime_type

    def extract_profile_audio(self, profile_id: str, force: bool = False) -> ArchiveMediaResult:
        videos = [
            asset
            for asset in self.repo.list_assets(profile_id)
            if asset.kind == "video" and asset.local_path
        ]
        existing_audio = {
            asset.metadata.get("source_video_asset_id")
            for asset in self.repo.list_assets(profile_id)
            if asset.kind == "audio"
        }
        result = ArchiveMediaResult(attempted=len(videos), failures=[])
        audio_assets: list[MediaAsset] = []
        for video in videos:
            if video.id in existing_audio and not force:
                result.skipped += 1
                continue
            try:
                path = self._extract_audio(video)
            except Exception as exc:
                result.failed += 1
                if len(result.failures) < 50:
                    result.failures.append(f"{video.id}: {type(exc).__name__}: {exc}")
                continue
            audio_assets.append(
                MediaAsset(
                    id=stable_id(video.id, "audio"),
                    item_id=video.item_id,
                    kind="audio",
                    local_path=str(path),
                    mime_type="audio/mpeg",
                    metadata={
                        "source": "ffmpeg_audio_extract",
                        "source_video_asset_id": video.id,
                        "source_video_url": video.url,
                    },
                )
            )
            result.downloaded += 1
        self.repo.upsert_assets(audio_assets)
        return result

    def _extract_audio(self, video: MediaAsset) -> Path:
        source = Path(video.local_path or "")
        if not source.exists():
            raise FileNotFoundError(source)
        directory = ensure_dir(self.archive_root / "audio" / video.id[:2])
        path = directory / f"{stable_id(video.id, source.stat().st_size)}.mp3"
        if path.exists() and path.stat().st_size > 0:
            return path
        ffmpeg = _ffmpeg_executable()
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(path),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode != 0 or not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("ffmpeg audio extraction failed")
        return path


def _guess_mime(url: str, data: bytes) -> str | None:
    guessed = mimetypes.guess_type(urlparse(url).path)[0]
    if guessed:
        return guessed
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:12].find(b"ftyp") >= 0:
        return "video/mp4"
    if b"-->" in data[:500]:
        return "text/plain"
    return None


def _suffix_for(url: str, mime_type: str | None) -> str:
    suffix = Path(urlparse(url).path).suffix
    if suffix:
        return suffix[:12]
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            return guessed
    return ".bin"


def _ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"
