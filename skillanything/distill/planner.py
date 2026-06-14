"""Plan capability distillation before generating a Skill.

The planner is intentionally domain-agnostic. It reads the collected corpus and
the user's goal, then decides what kind of capability should be extracted, what
evidence to look for, and how the distilled Skill should be evaluated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from skillanything.models import ProfileBundle
from skillanything.utils import stable_id, truncate, utc_now


@dataclass(slots=True)
class DistillationTask:
    id: str
    title: str
    purpose: str
    evidence_questions: list[str] = field(default_factory=list)
    output_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DistillationPlan:
    id: str
    profile_id: str
    goal: str
    capability_type: str
    domain: str
    audience: str
    skill_name_hint: str
    source_mix: dict[str, Any]
    extraction_targets: list[str]
    evidence_questions: list[str]
    workflow_axes: list[str]
    style_axes: list[str]
    guardrails: list[str]
    eval_scenarios: list[str]
    output_schema: dict[str, Any]
    tasks: list[DistillationTask]
    confidence: float
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DistillationPlanner:
    """Local planner agent for deciding how to distill a heterogeneous corpus."""

    def plan(
        self,
        bundle: ProfileBundle,
        *,
        goal: str | None = None,
        capability_type: str = "analysis_method",
        schema: dict[str, Any] | None = None,
    ) -> DistillationPlan:
        text = _bundle_text(bundle, limit=60000)
        goal_text = (goal or "").strip()
        domain = _detect_domain(text, goal_text, capability_type)
        spec = _DOMAIN_SPECS.get(domain, _DOMAIN_SPECS["generic"])
        profile_name = bundle.profile.display_name or bundle.profile.handle or bundle.profile.platform
        source_mix = {
            "platform": bundle.profile.platform,
            "items": len(bundle.items),
            "segments": len(bundle.segments),
            "assets": len(bundle.assets),
            "comments": len(bundle.comments),
            "has_media": bool(bundle.assets or bundle.segments),
            "has_comments": bool(bundle.comments),
        }
        output_schema = _merge_schema(spec["schema"], schema or {})
        output_fields = _schema_fields(output_schema)
        tasks = [
            DistillationTask(
                id=stable_id("distillation-task", bundle.profile.id, domain, index, task["title"]),
                title=task["title"],
                purpose=task["purpose"],
                evidence_questions=task.get("evidence_questions", [])[:],
                output_fields=task.get("output_fields", output_fields)[:],
            )
            for index, task in enumerate(spec["tasks"])
        ]
        skill_name = _skill_name(
            profile_name=str(profile_name),
            goal=goal_text,
            domain_label=spec["label"],
            capability_type=capability_type,
        )
        evidence_questions = [
            *_dedupe(spec["evidence_questions"]),
            *_custom_schema_questions(output_schema),
        ][:12]
        confidence = _plan_confidence(text=text, goal=goal_text, domain=domain, source_mix=source_mix)
        return DistillationPlan(
            id=stable_id(
                "distillation-plan",
                bundle.profile.id,
                goal_text,
                capability_type,
                domain,
                len(bundle.items),
                len(bundle.segments),
            ),
            profile_id=bundle.profile.id,
            goal=goal_text,
            capability_type=capability_type,
            domain=domain,
            audience=spec["audience"],
            skill_name_hint=skill_name,
            source_mix=source_mix,
            extraction_targets=spec["targets"][:],
            evidence_questions=evidence_questions,
            workflow_axes=spec["workflow_axes"][:],
            style_axes=spec["style_axes"][:],
            guardrails=_guardrails(source_mix, spec["guardrails"]),
            eval_scenarios=spec["eval_scenarios"][:],
            output_schema=output_schema,
            tasks=tasks,
            confidence=confidence,
        )


def plan_to_prompt(plan: DistillationPlan) -> str:
    tasks = "\n".join(
        f"- {task.title}: {task.purpose}; evidence={'; '.join(task.evidence_questions[:3])}"
        for task in plan.tasks
    )
    schema_fields = ", ".join(_schema_fields(plan.output_schema))
    return "\n".join(
        [
            "Distillation plan:",
            f"- capability_type: {plan.capability_type}",
            f"- domain: {plan.domain}",
            f"- goal: {plan.goal or 'autonomously discover the reusable capability'}",
            f"- audience: {plan.audience}",
            f"- skill_name_hint: {plan.skill_name_hint}",
            f"- extraction_targets: {', '.join(plan.extraction_targets)}",
            f"- workflow_axes: {', '.join(plan.workflow_axes)}",
            f"- style_axes: {', '.join(plan.style_axes)}",
            f"- guardrails: {'; '.join(plan.guardrails)}",
            f"- output_schema_fields: {schema_fields}",
            "Tasks:",
            tasks,
        ]
    )


def _bundle_text(bundle: ProfileBundle, limit: int) -> str:
    parts: list[str] = []
    for item in bundle.items:
        parts.append(item.title)
        parts.append(item.text)
    for segment in bundle.segments:
        parts.append(segment.text)
    for comment in bundle.comments:
        parts.append(comment.text)
    return truncate("\n".join(part for part in parts if part), limit)


def _detect_domain(text: str, goal: str, capability_type: str) -> str:
    haystack = f"{goal}\n{capability_type}\n{text}".lower()
    scores = {
        domain: sum(1 for keyword in spec["keywords"] if keyword.lower() in haystack)
        for domain, spec in _DOMAIN_SPECS.items()
        if domain != "generic"
    }
    if scores:
        domain, score = max(scores.items(), key=lambda item: item[1])
        if score > 0:
            return domain
    if capability_type and capability_type != "analysis_method":
        return capability_type
    return "generic"


def _merge_schema(default_schema: dict[str, Any], custom_schema: dict[str, Any]) -> dict[str, Any]:
    merged = dict(default_schema)
    for key, value in custom_schema.items():
        if key == "outputs" and isinstance(value, list):
            base = list(merged.get("outputs", []))
            merged["outputs"] = _dedupe([*base, *[str(item) for item in value]])
        else:
            merged[key] = value
    return merged


def _schema_fields(schema: dict[str, Any]) -> list[str]:
    outputs = schema.get("outputs")
    if isinstance(outputs, list):
        return [str(item) for item in outputs if str(item).strip()]
    return [str(key) for key in schema.keys()] or ["principles", "workflow", "evidence"]


def _custom_schema_questions(schema: dict[str, Any]) -> list[str]:
    return [f"What source evidence supports the `{field}` output field?" for field in _schema_fields(schema)[:6]]


def _guardrails(source_mix: dict[str, Any], base: list[str]) -> list[str]:
    guardrails = list(base)
    guardrails.append("Do not impersonate the original creator or infer private information.")
    guardrails.append("Separate observed evidence from inferred reusable procedure.")
    if not source_mix.get("has_comments"):
        guardrails.append("Do not infer audience reaction patterns when comments are unavailable.")
    if not source_mix.get("has_media"):
        guardrails.append("Do not infer visual, audio, or editing tactics without media evidence.")
    return _dedupe(guardrails)[:10]


def _plan_confidence(
    *,
    text: str,
    goal: str,
    domain: str,
    source_mix: dict[str, Any],
) -> float:
    score = 0.45
    if goal:
        score += 0.12
    if domain != "generic":
        score += 0.12
    score += min(int(source_mix.get("items") or 0), 8) * 0.025
    if len(text) > 3000:
        score += 0.08
    return min(0.9, round(score, 2))


def _skill_name(
    *,
    profile_name: str,
    goal: str,
    domain_label: str,
    capability_type: str,
) -> str:
    if goal:
        return f"{profile_name} {truncate(goal, 48)} Skill"
    if capability_type and capability_type != "analysis_method":
        return f"{profile_name} {capability_type.replace('_', ' ').title()} Skill"
    return f"{profile_name} {domain_label} Skill"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in result:
            result.append(clean)
    return result


_DOMAIN_SPECS: dict[str, dict[str, Any]] = {
    "trading_strategy": {
        "label": "Trading Strategy",
        "keywords": [
            "实盘",
            "交易",
            "买入",
            "卖出",
            "仓位",
            "止损",
            "复盘",
            "打板",
            "低吸",
            "龙头",
            "k线",
            "分时",
            "回撤",
            "盈亏",
            "position",
            "stop loss",
            "setup",
        ],
        "audience": "traders or analysts who need repeatable decision rules without copying trades",
        "targets": ["market setup", "entry trigger", "exit trigger", "position sizing", "risk control", "review loop"],
        "evidence_questions": [
            "What conditions repeatedly appear before action is taken?",
            "How are entry, add, reduce, and exit decisions separated?",
            "What risk limits, invalidation points, or review rules are explicit?",
        ],
        "workflow_axes": ["setup recognition", "signal confirmation", "execution", "risk control", "post-trade review"],
        "style_axes": ["probabilistic language", "clear invalidation", "no trade copying", "risk-first framing"],
        "guardrails": [
            "Do not present examples as financial advice.",
            "Do not invent exact holdings, returns, or private execution records.",
        ],
        "eval_scenarios": [
            "Given a new market note, identify setup, trigger, risk, and invalidation.",
            "Given a losing trade narrative, extract the review checklist without hindsight bias.",
        ],
        "schema": {"outputs": ["setup", "signal", "execution", "risk", "review", "evidence"]},
        "tasks": [
            {
                "title": "Map repeatable setups",
                "purpose": "Find recurring preconditions and market states.",
                "evidence_questions": ["Which words describe setup quality?", "What context is required before action?"],
            },
            {
                "title": "Extract execution rules",
                "purpose": "Separate entry, exit, sizing, and stop logic.",
                "evidence_questions": ["What triggers action?", "What cancels the thesis?"],
            },
            {
                "title": "Define risk and review loop",
                "purpose": "Turn post-trade reflection into reusable guardrails.",
                "evidence_questions": ["How are mistakes diagnosed?", "Which risks are repeatedly named?"],
            },
        ],
    },
    "marketing_growth": {
        "label": "Marketing Growth",
        "keywords": [
            "小红书",
            "种草",
            "广告",
            "投放",
            "达人",
            "品牌",
            "转化",
            "私域",
            "爆文",
            "封面",
            "标题",
            "评论区",
            "素材",
            "roi",
            "kol",
            "ugc",
            "campaign",
        ],
        "audience": "marketers who need reusable campaign, content, and conversion playbooks",
        "targets": ["audience insight", "hook", "creative format", "channel tactic", "conversion path", "measurement"],
        "evidence_questions": [
            "Which audience pain points, hooks, or objections recur?",
            "What creative structure links title, cover, body, and call to action?",
            "How are conversion, retention, or private-domain actions measured?",
        ],
        "workflow_axes": ["audience selection", "content hook", "creative production", "distribution", "conversion", "iteration"],
        "style_axes": ["customer-language first", "specific claims", "platform-native tone", "measurable CTA"],
        "guardrails": [
            "Do not infer private ad spend, conversion rate, or client results without evidence.",
            "Separate brand positioning from tactical copy patterns.",
        ],
        "eval_scenarios": [
            "Given a product brief, generate a platform-native content plan with evidence-backed assumptions.",
            "Given a failed post, diagnose hook, audience, creative, distribution, and conversion issues.",
        ],
        "schema": {"outputs": ["audience", "hook", "creative", "channel", "conversion", "metrics", "evidence"]},
        "tasks": [
            {
                "title": "Extract audience and hook logic",
                "purpose": "Identify who the content speaks to and what makes them pay attention.",
                "evidence_questions": ["Which pain points are named?", "Which titles or openings are repeated?"],
            },
            {
                "title": "Map creative and channel pattern",
                "purpose": "Turn posts, media, and comments into reusable content rules.",
                "evidence_questions": ["What format is used?", "What platform affordance is being exploited?"],
            },
            {
                "title": "Define conversion and measurement loop",
                "purpose": "Capture CTA, lead flow, and iteration signals.",
                "evidence_questions": ["What action is requested?", "What metrics or feedback loops are visible?"],
            },
        ],
    },
    "industry_research": {
        "label": "Industry Research",
        "keywords": [
            "产业链",
            "公司",
            "供应链",
            "上游",
            "下游",
            "竞争格局",
            "收入",
            "毛利",
            "客户",
            "订单",
            "产能",
            "估值",
            "a股",
            "robot",
            "supply chain",
        ],
        "audience": "researchers who need evidence-backed maps from industry facts to decisions",
        "targets": ["chain node", "company mapping", "causal mechanism", "evidence strength", "watchlist"],
        "evidence_questions": [
            "What entities, nodes, and relationships are explicitly supported?",
            "Which links are factual and which are inferred?",
            "What indicators would confirm or falsify the relationship?",
        ],
        "workflow_axes": ["taxonomy", "entity mapping", "mechanism", "evidence grading", "monitoring"],
        "style_axes": ["evidence-first", "distinguish fact from inference", "confidence labels"],
        "guardrails": ["Do not invent company relationships or financial data."],
        "eval_scenarios": [
            "Given an industry topic, produce a chain map with supported and uncertain nodes.",
            "Given a company list, classify relevance and missing evidence.",
        ],
        "schema": {"outputs": ["chain", "entities", "mechanism", "evidence", "confidence", "watchlist"]},
        "tasks": [
            {
                "title": "Build relationship map",
                "purpose": "Identify entities, chain nodes, and relationship types.",
                "evidence_questions": ["Which relationship is directly stated?", "Which node is inferred?"],
            },
            {
                "title": "Grade evidence strength",
                "purpose": "Separate direct evidence, weak signal, and hypothesis.",
                "evidence_questions": ["What quote supports the link?", "What data is missing?"],
            },
        ],
    },
    "generic": {
        "label": "Reusable Method",
        "keywords": [],
        "audience": "users who need a reusable method distilled from public evidence",
        "targets": ["goal", "inputs", "decision rules", "workflow", "outputs", "limits"],
        "evidence_questions": [
            "What repeated actions, judgments, or procedures appear in the corpus?",
            "What inputs are required before the capability can be applied?",
            "What outputs and quality checks make the capability useful?",
        ],
        "workflow_axes": ["input reading", "pattern extraction", "decision rule", "output", "quality check"],
        "style_axes": ["clear assumptions", "evidence-backed claims", "reusable procedure", "explicit limits"],
        "guardrails": ["Do not overfit a single example into a universal rule."],
        "eval_scenarios": [
            "Given a new case, apply the extracted method and state assumptions.",
            "Given insufficient evidence, explain what cannot be concluded.",
        ],
        "schema": {"outputs": ["inputs", "rules", "workflow", "outputs", "evidence", "limits"]},
        "tasks": [
            {
                "title": "Identify reusable behavior",
                "purpose": "Find repeated moves, decisions, and quality checks.",
                "evidence_questions": ["What repeats across documents?", "What appears to be context-specific?"],
            },
            {
                "title": "Convert evidence into procedure",
                "purpose": "Turn observations into steps that an agent can execute.",
                "evidence_questions": ["What is the required input?", "What output should be produced?"],
            },
        ],
    },
}
