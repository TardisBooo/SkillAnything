"""Capability distillation orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from skillanything.config import Settings
from skillanything.distill.distiller import Distiller
from skillanything.distill.planner import DistillationPlan, DistillationPlanner
from skillanything.ir import (
    Capability,
    CapabilityRequest,
    Corpus,
    SkillPack,
    capability_from_skill,
    corpus_from_bundle,
    skill_pack_from_capability,
)
from skillanything.models import DistilledSkill, ProfileBundle


@dataclass(slots=True)
class DistillationRun:
    corpus: Corpus
    plan: DistillationPlan
    skill: DistilledSkill
    capability: Capability
    pack: SkillPack


class CapabilityDistillationPipeline:
    """Distill ProfileBundles into reusable, reviewable capabilities."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def discover(
        self,
        bundle: ProfileBundle,
        *,
        goal: str = "",
        item_limit: int | None = None,
        target_surfaces: list[str] | None = None,
    ) -> DistillationRun:
        corpus = corpus_from_bundle(bundle, goal=goal, item_limit=item_limit)
        plan = DistillationPlanner().plan(
            bundle,
            goal=goal,
            capability_type="analysis_method",
        )
        corpus.metadata["distillation_plan"] = plan.to_dict()
        skill = Distiller(self.settings).distill(
            bundle,
            focus=goal or None,
            plan=plan,
            capability_type=plan.capability_type,
            schema=plan.output_schema,
        )
        capability = capability_from_skill(
            skill,
            corpus_id=corpus.id,
            capability_type="analysis_method",
            origin="auto",
        )
        pack = skill_pack_from_capability(
            capability,
            skill,
            corpus,
            target_surfaces=target_surfaces,
        )
        return DistillationRun(
            corpus=corpus,
            plan=plan,
            skill=skill,
            capability=capability,
            pack=pack,
        )

    def extract(
        self,
        bundle: ProfileBundle,
        request: CapabilityRequest,
        *,
        item_limit: int | None = None,
        target_surfaces: list[str] | None = None,
    ) -> DistillationRun:
        corpus = corpus_from_bundle(
            bundle,
            goal=request.instructions or request.label,
            item_limit=item_limit,
            capability_requests=[request],
        )
        plan = DistillationPlanner().plan(
            bundle,
            goal=request.instructions or request.label,
            capability_type=request.type,
            schema=request.schema,
        )
        corpus.metadata["distillation_plan"] = plan.to_dict()
        skill = Distiller(self.settings).distill(
            bundle,
            focus=request.instructions or request.label,
            plan=plan,
            capability_type=request.type,
            schema=request.schema,
        )
        capability = capability_from_skill(
            skill,
            corpus_id=corpus.id,
            capability_type=request.type,
            origin=request.origin,
            request=request,
        )
        pack = skill_pack_from_capability(
            capability,
            skill,
            corpus,
            target_surfaces=target_surfaces,
        )
        return DistillationRun(
            corpus=corpus,
            plan=plan,
            skill=skill,
            capability=capability,
            pack=pack,
        )
