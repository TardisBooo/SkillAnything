"""Application service layer."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from skillanything.config import Settings, load_settings
from skillanything.connectors import build_connector
from skillanything.connectors.base import FetchRequest
from skillanything.distill.pipeline import CapabilityDistillationPipeline, DistillationRun
from skillanything.extract.multimodal import MultimodalExtractor
from skillanything.ir import (
    CapabilityRequest,
    capability_request_from_focus,
    corpus_from_bundle,
)
from skillanything.media_archive import ArchiveMediaResult, MediaArchiver
from skillanything.models import CollectResult, DistilledSkill, ProfileBundle
from skillanything.package.exporters import SkillPackExporter
from skillanything.package.writer import SkillPackageWriter
from skillanything.qa import KnowledgeQA
from skillanything.storage.repository import Repository
from skillanything.utils import stable_id, utc_now


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
        self.repo.save_collection_run(
            profile_id=result.profile.id,
            source=source,
            platform=platform or result.profile.platform,
            request={
                "source": source,
                "platform": platform,
                "max_items": max_items,
                "include_comments": include_comments,
                "include_media": include_media,
                "deep": deep,
                "media_max_assets": media_max_assets,
            },
            diagnostics=result.diagnostics,
            counts={
                "items": len(result.items),
                "segments": len(result.segments),
                "assets": len(result.assets),
                "comments": len(result.comments),
            },
        )
        return result

    def distill(self, profile_id: str, item_limit: int = 200) -> DistilledSkill:
        self.init()
        bundle = self.repo.load_bundle(profile_id, item_limit=item_limit)
        run = CapabilityDistillationPipeline(self.settings).discover(
            bundle,
            item_limit=item_limit,
            target_surfaces=["codex-skill", "openai-skill", "claude-skill"],
        )
        self._persist_distillation_run(run)
        self.repo.rebuild_search_index(profile_id)
        return run.skill

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
        request = capability_request_from_focus(focus)
        run = CapabilityDistillationPipeline(self.settings).extract(
            bundle,
            request,
            item_limit=item_limit,
            target_surfaces=["codex-skill", "openai-skill", "claude-skill"],
        )
        self._persist_distillation_run(run)
        self.repo.rebuild_search_index(profile_id)
        return run.skill

    def build_corpus(
        self,
        profile_id: str,
        *,
        goal: str = "",
        item_limit: int = 1000,
        capability_requests: list[CapabilityRequest] | None = None,
    ) -> dict:
        self.init()
        if not self.repo.get_profile(profile_id):
            raise KeyError(f"profile not found: {profile_id}")
        bundle = self.repo.load_bundle(profile_id, item_limit=item_limit)
        corpus = corpus_from_bundle(
            bundle,
            goal=goal,
            item_limit=item_limit,
            capability_requests=capability_requests,
        )
        return self.repo.save_corpus(corpus)

    def discover_capability(
        self,
        profile_id: str,
        *,
        goal: str = "",
        item_limit: int = 200,
    ) -> dict:
        self.init()
        if not self.repo.get_profile(profile_id):
            raise KeyError(f"profile not found: {profile_id}")
        bundle = self.repo.load_bundle(profile_id, item_limit=item_limit)
        run = CapabilityDistillationPipeline(self.settings).discover(
            bundle,
            goal=goal,
            item_limit=item_limit,
            target_surfaces=["codex-skill", "openai-skill", "claude-skill"],
        )
        self._persist_distillation_run(run)
        self.repo.rebuild_search_index(profile_id)
        return run.capability.to_dict()

    def extract_capability(
        self,
        profile_id: str,
        *,
        focus: str,
        capability_type: str = "analysis_method",
        item_limit: int = 80,
        schema: dict | None = None,
    ) -> dict:
        self.init()
        request = capability_request_from_focus(
            focus,
            capability_type=capability_type,
            schema=schema,
        )
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
        run = CapabilityDistillationPipeline(self.settings).extract(
            bundle,
            request,
            item_limit=item_limit,
            target_surfaces=["codex-skill", "openai-skill", "claude-skill"],
        )
        self._persist_distillation_run(run)
        self.repo.rebuild_search_index(profile_id)
        return run.capability.to_dict()

    def create_skill_pack(
        self,
        capability_id: str,
        *,
        target_surfaces: list[str] | None = None,
    ) -> dict:
        self.init()
        capability = self.repo.get_capability(capability_id)
        if not capability:
            raise KeyError(f"capability not found: {capability_id}")
        existing = self.repo.list_skill_packs(capability_id=capability_id, limit=1)
        if existing:
            return existing[0]
        skill_id = capability.get("metadata", {}).get("skill_id")
        skill = self.repo.get_skill_json(str(skill_id)) if skill_id else None
        if not skill:
            raise KeyError(f"skill not found for capability: {capability_id}")
        corpus = self.repo.get_corpus(str(capability["corpus_id"])) or {}
        pack = {
            "id": stable_id(
                "skill-pack",
                capability_id,
                skill.get("id"),
                ",".join(target_surfaces or ["codex-skill"]),
            ),
            "capability_id": capability_id,
            "profile_id": capability["profile_id"],
            "skill_id": skill.get("id"),
            "title": capability.get("name") or skill.get("title") or "Skill Pack",
            "version": skill.get("version") or "0.1.0",
            "target_surfaces": target_surfaces or ["codex-skill"],
            "skill_json": skill,
            "capability": capability,
            "corpus": corpus,
            "metadata": {
                "artifact_schema": "skillanything.skill_pack.v1",
                "created_from": "create_skill_pack",
            },
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        return self.repo.save_skill_pack(pack)

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

    def export(
        self,
        skill_id: str,
        output_root: Path | None = None,
        *,
        target: str = "codex-skill",
    ) -> Path:
        self.init()
        skill = self.repo.get_skill_json(skill_id)
        if not skill:
            raise KeyError(f"skill not found: {skill_id}")
        profile_id = skill.get("profile_id")
        bundle = self.repo.load_bundle(profile_id, item_limit=1000) if profile_id else None
        pack = self.repo.find_skill_pack_by_skill(skill_id)
        if pack:
            artifact = SkillPackExporter().export(
                pack,
                output_root or self.settings.output_dir,
                target=target,
                bundle=bundle,
            )
            path = Path(artifact.path)
            self.repo.save_export_artifact(
                pack_id=pack.get("id"),
                skill_id=skill_id,
                target=target,
                path=str(path),
                artifact=artifact.to_dict(),
            )
        else:
            writer = SkillPackageWriter()
            path = writer.write(skill, output_root or self.settings.output_dir, bundle=bundle)
            self.repo.save_export_artifact(
                pack_id=None,
                skill_id=skill_id,
                target="codex-skill",
                path=str(path),
                artifact={"target": "codex-skill", "path": str(path), "legacy": True},
            )
        self.repo.save_skill_json_output(skill_id, str(path))
        if profile_id:
            self.repo.rebuild_search_index(profile_id)
        return path

    def export_pack(
        self,
        pack_id: str,
        *,
        target: str = "codex-skill",
        output_root: Path | None = None,
    ) -> dict:
        self.init()
        pack = self.repo.get_skill_pack(pack_id)
        if not pack:
            raise KeyError(f"skill pack not found: {pack_id}")
        profile_id = pack.get("profile_id")
        bundle = self.repo.load_bundle(profile_id, item_limit=1000) if profile_id else None
        artifact = SkillPackExporter().export(
            pack,
            output_root or self.settings.output_dir,
            target=target,
            bundle=bundle,
        )
        self.repo.save_export_artifact(
            pack_id=pack_id,
            skill_id=pack.get("skill_id"),
            target=target,
            path=artifact.path,
            artifact=artifact.to_dict(),
        )
        if pack.get("skill_id"):
            self.repo.save_skill_json_output(str(pack["skill_id"]), artifact.path)
        return artifact.to_dict()

    def _persist_distillation_run(self, run: DistillationRun) -> None:
        self.repo.save_skill(run.skill)
        self.repo.save_corpus(run.corpus)
        self.repo.save_capability(run.capability)
        self.repo.save_skill_pack(run.pack)


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
