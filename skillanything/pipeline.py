"""Application service layer."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from skillanything.config import Settings, load_settings
from skillanything.connectors import build_connector
from skillanything.connectors.base import FetchRequest
from skillanything.distill.distiller import Distiller
from skillanything.extract.multimodal import MultimodalExtractor
from skillanything.media_archive import ArchiveMediaResult, MediaArchiver
from skillanything.models import CollectResult, DistilledSkill, ProfileBundle
from skillanything.package.writer import SkillPackageWriter
from skillanything.qa import KnowledgeQA
from skillanything.storage.repository import Repository


@dataclass(slots=True)
class MediaAnalysisResult:
    attempted: int = 0
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    segments: int = 0
    failures: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "analyzed": self.analyzed,
            "skipped": self.skipped,
            "failed": self.failed,
            "segments": self.segments,
            "failures": self.failures or [],
        }


class SkillAnythingApp:
    def __init__(self, settings: Settings | None = None) -> None:
        self._explicit_settings = settings is not None
        self.settings = settings or load_settings()
        self.repo = Repository(self.settings.db_path)

    def init(self) -> None:
        self.settings.home.mkdir(parents=True, exist_ok=True)
        self.settings.archive_dir.mkdir(parents=True, exist_ok=True)
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        self.repo.init_schema()
        if not self._explicit_settings:
            self._apply_saved_settings()

    def _apply_saved_settings(self) -> None:
        values = self.repo.get_app_settings()

        def value(key: str, fallback):
            raw = values.get(key)
            return raw if raw not in {None, ""} else fallback

        media_max_assets = self.settings.media_max_assets
        raw_media_limit = values.get("SKILLANYTHING_MEDIA_MAX_ASSETS")
        if raw_media_limit:
            try:
                media_max_assets = int(raw_media_limit)
            except ValueError:
                media_max_assets = self.settings.media_max_assets

        self.settings = replace(
            self.settings,
            llm_base_url=value("SKILLANYTHING_LLM_BASE_URL", self.settings.llm_base_url),
            llm_api_key=value("SKILLANYTHING_LLM_API_KEY", self.settings.llm_api_key),
            llm_model=value("SKILLANYTHING_LLM_MODEL", self.settings.llm_model),
            vision_base_url=value("SKILLANYTHING_VISION_BASE_URL", self.settings.vision_base_url),
            vision_api_key=value("SKILLANYTHING_VISION_API_KEY", self.settings.vision_api_key),
            vision_model=value("SKILLANYTHING_VISION_MODEL", self.settings.vision_model),
            asr_base_url=value("SKILLANYTHING_ASR_BASE_URL", self.settings.asr_base_url),
            asr_api_key=value("SKILLANYTHING_ASR_API_KEY", self.settings.asr_api_key),
            asr_model=value("SKILLANYTHING_ASR_MODEL", self.settings.asr_model),
            asr_language=value("SKILLANYTHING_ASR_LANGUAGE", self.settings.asr_language),
            xueqiu_cookie=value("SKILLANYTHING_XUEQIU_COOKIE", self.settings.xueqiu_cookie),
            cdp_url=value("SKILLANYTHING_CDP_URL", self.settings.cdp_url),
            media_max_assets=media_max_assets,
        )

    def collect(
        self,
        source: str,
        platform: str | None = None,
        max_items: int = 50,
        include_comments: bool = False,
        include_media: bool = True,
        deep: bool = True,
        media_max_assets: int | None = None,
    ) -> CollectResult:
        self.init()
        request = FetchRequest(
            source=source,
            platform=platform,
            max_items=max_items,
            include_comments=include_comments,
            include_media=include_media,
            deep=deep,
        )
        connector = build_connector(self.settings, request)
        result = connector.collect(request)
        if include_media:
            extractor_settings = (
                replace(self.settings, media_max_assets=media_max_assets)
                if media_max_assets is not None
                else self.settings
            )
            result.segments.extend(MultimodalExtractor(extractor_settings).extract(result))
        self.repo.upsert_profile(result.profile)
        self.repo.upsert_items(result.items)
        self.repo.upsert_assets(result.assets)
        self.repo.upsert_segments(result.segments)
        self.repo.upsert_comments(result.comments)
        self.repo.rebuild_search_index(result.profile.id)
        result.diagnostics.insert(0, f"connector={connector.name}")
        return result

    def distill(self, profile_id: str, item_limit: int = 200) -> DistilledSkill:
        self.init()
        bundle = self.repo.load_bundle(profile_id, item_limit=item_limit)
        skill = Distiller(self.settings).distill(bundle)
        self.repo.save_skill(skill)
        self.repo.rebuild_search_index(profile_id)
        return skill

    def full_run(
        self,
        source: str,
        platform: str | None = None,
        max_items: int = 50,
        include_comments: bool = False,
        include_media: bool = True,
        deep: bool = True,
        media_max_assets: int | None = None,
        item_limit: int = 200,
        output_root: Path | None = None,
    ) -> dict:
        collect_result = self.collect(
            source=source,
            platform=platform,
            max_items=max_items,
            include_comments=include_comments,
            include_media=include_media,
            deep=deep,
            media_max_assets=media_max_assets,
        )
        skill = self.distill(collect_result.profile.id, item_limit=item_limit)
        output_path = self.export(skill.id, output_root=output_root)
        return {
            "profile": collect_result.profile.to_dict(),
            "skill": skill.to_dict(),
            "output_path": str(output_path),
            "counts": {
                "items": len(collect_result.items),
                "segments": len(collect_result.segments),
                "assets": len(collect_result.assets),
                "comments": len(collect_result.comments),
            },
            "diagnostics": collect_result.diagnostics,
        }

    def ask(self, profile_id: str, question: str, limit: int = 8) -> dict:
        self.init()
        if not self.repo.get_profile(profile_id):
            raise KeyError(f"profile not found: {profile_id}")
        return KnowledgeQA(self.settings, self.repo).ask(profile_id, question, limit=limit)

    def extract_focused_skill(
        self,
        profile_id: str,
        focus: str,
        item_limit: int = 80,
    ) -> DistilledSkill:
        self.init()
        profile = self.repo.get_profile(profile_id)
        if not profile:
            raise KeyError(f"profile not found: {profile_id}")
        if self.repo.count_search_documents(profile_id) == 0:
            self.repo.rebuild_search_index(profile_id)
        docs = self.repo.search_documents(profile_id, focus, limit=item_limit)
        item_ids = []
        for doc in docs:
            item_id = doc.get("item_id")
            if item_id and item_id not in item_ids:
                item_ids.append(item_id)
        bundle = self.repo.load_bundle(profile_id, item_limit=1000)
        if item_ids:
            bundle = _filter_bundle(bundle, item_ids)
        skill = Distiller(self.settings).distill(bundle, focus=focus)
        self.repo.save_skill(skill)
        self.repo.rebuild_search_index(profile_id)
        return skill

    def archive_media(
        self,
        profile_id: str,
        kinds: set[str] | None = None,
        limit: int | None = None,
        force: bool = False,
        workers: int = 12,
    ) -> ArchiveMediaResult:
        self.init()
        return MediaArchiver(self.repo, self.settings.archive_dir).archive_profile(
            profile_id=profile_id,
            kinds=kinds,
            limit=limit,
            force=force,
            workers=workers,
        )

    def extract_audio(self, profile_id: str, force: bool = False) -> ArchiveMediaResult:
        self.init()
        return MediaArchiver(self.repo, self.settings.archive_dir).extract_profile_audio(
            profile_id=profile_id,
            force=force,
        )

    def analyze_media(
        self,
        profile_id: str,
        item_id: str | None = None,
        source_id: str | None = None,
        kinds: set[str] | None = None,
        limit: int | None = None,
        force: bool = False,
        workers: int = 1,
    ) -> MediaAnalysisResult:
        self.init()
        profile = self.repo.get_profile(profile_id)
        if not profile:
            raise KeyError(f"profile not found: {profile_id}")
        item = self.repo.find_item(profile_id, item_id=item_id, source_id=source_id)
        if (item_id or source_id) and not item:
            raise KeyError(f"item not found: item_id={item_id or ''} source_id={source_id or ''}")
        target_item_id = item.id if item else None
        target_kinds = kinds or {"image", "video", "audio"}
        assets = [
            asset
            for asset in self.repo.list_assets(profile_id=profile_id, item_id=target_item_id)
            if asset.kind in target_kinds
        ]
        existing_segments = self.repo.list_segments(profile_id=profile_id, item_id=target_item_id)
        asset_by_id = {asset.id: asset for asset in assets}
        existing_asset_ids = {
            str(segment.metadata.get("asset_id"))
            for segment in existing_segments
            if segment.metadata.get("asset_id")
            and segment.source
            in {
                "vision:openai_compatible",
                "vision:video_frame",
                "asr:qwen3_asr_flash",
                "vision:pending",
                "video:pending",
            }
        }
        recognized_image_keys = {
            _image_equivalence_key(asset_by_id[asset_id])
            for asset_id in existing_asset_ids
            if asset_id in asset_by_id and asset_by_id[asset_id].kind == "image"
        }
        pending_assets = _dedupe_image_assets_for_analysis(
            assets,
            existing_asset_ids=existing_asset_ids if not force else set(),
            recognized_image_keys=recognized_image_keys if not force else set(),
        )
        if limit is not None:
            pending_assets = pending_assets[:limit]
        result = MediaAnalysisResult(
            attempted=len(pending_assets),
            skipped=len(assets) - len(pending_assets),
            failures=[],
        )
        if not pending_assets:
            return result

        settings = replace(self.settings, media_max_assets=max(1, len(pending_assets)))
        if force:
            self.repo.delete_multimodal_segments_for_assets(asset.id for asset in pending_assets)
        else:
            error_asset_ids = [
                asset.id
                for asset in pending_assets
                if any(
                    segment.source == "multimodal:error"
                    and segment.metadata.get("asset_id") == asset.id
                    for segment in existing_segments
                )
            ]
            self.repo.delete_multimodal_segments_for_assets(error_asset_ids)

        def work(asset):
            extractor = MultimodalExtractor(settings)
            try:
                collect_result = CollectResult(
                    profile=profile,
                    assets=[asset],
                    segments=existing_segments,
                )
                return asset.id, extractor.extract(collect_result), None
            except Exception as exc:
                return asset.id, [], f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(work, asset) for asset in pending_assets]
            for future in as_completed(futures):
                asset_id, segments, error = future.result()
                if error:
                    result.failed += 1
                    if len(result.failures) < 50:
                        result.failures.append(f"{asset_id}: {error}")
                    continue
                result.analyzed += 1
                result.segments += len(segments)
                self.repo.upsert_segments(segments)
        return result

    def export(self, skill_id: str, output_root: Path | None = None) -> Path:
        self.init()
        skill = self.repo.get_skill_json(skill_id)
        if not skill:
            raise KeyError(f"skill not found: {skill_id}")
        profile_id = skill.get("profile_id")
        bundle = self.repo.load_bundle(profile_id, item_limit=1000) if profile_id else None
        writer = SkillPackageWriter()
        path = writer.write(skill, output_root or self.settings.output_dir, bundle=bundle)
        self.repo.save_skill_json_output(skill_id, str(path))
        if profile_id:
            self.repo.rebuild_search_index(profile_id)
        return path


def _dedupe_image_assets_for_analysis(
    assets,
    existing_asset_ids: set[str],
    recognized_image_keys: set[tuple[str, str]],
):
    image_groups = {}
    non_images = []
    for asset in assets:
        if asset.kind != "image":
            if asset.id not in existing_asset_ids:
                non_images.append(asset)
            continue
        key = _image_equivalence_key(asset)
        if key in recognized_image_keys:
            continue
        image_groups.setdefault(key, []).append(asset)

    def score(asset):
        if asset.local_path:
            path = Path(asset.local_path)
            if path.exists():
                return path.stat().st_size
        return 0

    image_assets = [max(group, key=score) for group in image_groups.values()]
    return [*non_images, *image_assets]


def _image_equivalence_key(asset) -> tuple[str, str]:
    url = asset.url or asset.local_path or asset.id
    match = re.search(r"/(?:spectrum|notes_pre_post)/([^!?]+)", url)
    key = match.group(1) if match else url.split("!")[0].split("?")[0]
    return asset.item_id, key


def _filter_bundle(bundle: ProfileBundle, item_ids: list[str]) -> ProfileBundle:
    wanted = set(item_ids)
    order = {item_id: index for index, item_id in enumerate(item_ids)}
    items = [item for item in bundle.items if item.id in wanted]
    items.sort(key=lambda item: order.get(item.id, len(order)))
    return ProfileBundle(
        profile=bundle.profile,
        items=items,
        assets=[asset for asset in bundle.assets if asset.item_id in wanted],
        segments=[segment for segment in bundle.segments if segment.item_id in wanted],
        comments=[comment for comment in bundle.comments if comment.item_id in wanted],
    )
