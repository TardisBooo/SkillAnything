"""Distill normalized profile evidence into an agent-ready skill model."""

from __future__ import annotations

import json
import re
import urllib.request
from collections import Counter
from typing import Any

from skillanything.config import Settings
from skillanything.distill.planner import (
    DistillationPlan,
    DistillationPlanner,
    plan_to_prompt,
)
from skillanything.models import Citation, DistilledSkill, ProfileBundle
from skillanything.utils import stable_id, truncate


class Distiller:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def distill(
        self,
        bundle: ProfileBundle,
        focus: str | None = None,
        *,
        plan: DistillationPlan | None = None,
        capability_type: str = "analysis_method",
        schema: dict[str, Any] | None = None,
    ) -> DistilledSkill:
        plan = plan or DistillationPlanner().plan(
            bundle,
            goal=focus,
            capability_type=capability_type,
            schema=schema,
        )
        if self.settings.llm_api_key and self.settings.llm_base_url:
            try:
                return self._distill_with_compatible_chat(bundle, focus=focus, plan=plan)
            except Exception as exc:
                fallback = self._distill_locally(bundle, focus=focus, plan=plan)
                fallback.metadata["model_error"] = f"{type(exc).__name__}: {exc}"
                return fallback
        if self.settings.openai_api_key:
            try:
                return self._distill_with_openai(bundle, focus=focus, plan=plan)
            except Exception as exc:
                fallback = self._distill_locally(bundle, focus=focus, plan=plan)
                fallback.metadata["model_error"] = f"{type(exc).__name__}: {exc}"
                return fallback
        return self._distill_locally(bundle, focus=focus, plan=plan)

    def _distill_with_compatible_chat(
        self,
        bundle: ProfileBundle,
        focus: str | None = None,
        plan: DistillationPlan | None = None,
    ) -> DistilledSkill:
        plan = plan or DistillationPlanner().plan(bundle, goal=focus)
        model = self.settings.llm_model or self.settings.model or "qwen3-vl-plus"
        corpus = self._corpus(bundle, max_items=80, max_chars=60000)
        prompt = self._distill_prompt(corpus, focus=focus, plan=plan)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        data = _post_json(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            payload,
            self.settings.llm_api_key or "",
        )
        text = _chat_text(data)
        parsed = self._parse_json_object(text)
        return self._skill_from_model_data(
            bundle,
            parsed,
            distiller="openai_compatible_chat",
            model=model,
            focus=focus,
            plan=plan,
        )

    def _distill_with_openai(
        self,
        bundle: ProfileBundle,
        focus: str | None = None,
        plan: DistillationPlan | None = None,
    ) -> DistilledSkill:
        from openai import OpenAI

        plan = plan or DistillationPlanner().plan(bundle, goal=focus)
        client = OpenAI(api_key=self.settings.openai_api_key)
        model = self.settings.model or "gpt-5-mini"
        corpus = self._corpus(bundle, max_items=40, max_chars=30000)
        prompt = self._distill_prompt(corpus, focus=focus, plan=plan)
        response = client.responses.create(
            model=model,
            input=prompt,
        )
        text = getattr(response, "output_text", "") or str(response)
        data = self._parse_json_object(text)
        return self._skill_from_model_data(
            bundle,
            data,
            distiller="openai",
            model=model,
            focus=focus,
            plan=plan,
        )

    def _skill_from_model_data(
        self,
        bundle: ProfileBundle,
        data: dict[str, Any],
        distiller: str,
        model: str,
        focus: str | None = None,
        plan: DistillationPlan | None = None,
    ) -> DistilledSkill:
        plan = plan or DistillationPlanner().plan(bundle, goal=focus)
        citations = self._citations(bundle)
        model_reports = _as_research_reports(data.get("research_reports"))
        local_reports = self._research_reports(bundle, plan=plan)
        research_reports = _merge_reports(model_reports, local_reports)
        return DistilledSkill(
            id=stable_id(
                bundle.profile.id,
                "skill",
                plan.id,
                data.get("summary", ""),
            ),
            profile_id=bundle.profile.id,
            title=plan.skill_name_hint,
            version="0.1.0",
            summary=str(data.get("summary") or _summary_from_plan(bundle, plan)),
            principles=_as_str_list(data.get("principles"))[:12]
            or _principles_from_plan(plan, self._keywords(_bundle_text(bundle))),
            workflow=_as_str_list(data.get("workflow"))[:12] or _workflow_from_plan(plan),
            style_rules=_as_str_list(data.get("style_rules"))[:12] or _style_rules_from_plan(plan),
            blindspots=_as_str_list(data.get("blindspots"))[:12] or plan.guardrails[:8],
            eval_cases=_as_eval_cases(data.get("eval_cases")) or _eval_cases_from_plan(plan),
            citations=citations,
            metadata={
                "distiller": distiller,
                "model": model,
                "item_count": len(bundle.items),
                "segment_count": len(bundle.segments),
                "comment_count": len(bundle.comments),
                "research_reports": research_reports,
                "focus": focus or "",
                "domain": plan.domain,
                "capability_type": plan.capability_type,
                "distillation_plan": plan.to_dict(),
            },
        )

    @staticmethod
    def _distill_prompt(
        corpus: str,
        focus: str | None = None,
        plan: DistillationPlan | None = None,
    ) -> str:
        focus_line = f"User goal: {focus.strip()}\n" if focus and focus.strip() else ""
        plan_text = plan_to_prompt(plan) if plan else "Distillation plan: infer from evidence."
        return (
            "You are a general-purpose AI Skill distillation planner and builder. "
            "Use the public evidence below to extract a reusable capability for an agent. "
            "Do not impersonate the source creator. Do not force the corpus into a finance, "
            "macro, marketing, trading, research, writing, or education template unless the "
            "plan and evidence support it. Separate observed evidence from inferred reusable "
            "procedure, and preserve uncertainty.\n"
            f"{focus_line}"
            f"{plan_text}\n\n"
            "Return only a JSON object, no Markdown. Required fields: "
            "summary, principles, workflow, style_rules, blindspots, research_reports, eval_cases.\n"
            "principles/workflow/style_rules/blindspots must be string arrays. "
            "research_reports must be an array of objects with title, source_url, question, "
            "indicators, tools, transmission_chain, conclusion. "
            "eval_cases must be an array of objects with name, input, expected_behavior.\n\n"
            f"Evidence corpus:\n{corpus}"
        )

    def _distill_locally(
        self,
        bundle: ProfileBundle,
        focus: str | None = None,
        plan: DistillationPlan | None = None,
    ) -> DistilledSkill:
        plan = plan or DistillationPlanner().plan(bundle, goal=focus)
        corpus_text = _bundle_text(bundle)
        keywords = self._keywords(corpus_text)
        top_items = bundle.items[: min(8, len(bundle.items))]
        summary = _summary_from_plan(bundle, plan)
        if top_items:
            titles = "; ".join(truncate(item.title, 40) for item in top_items[:3])
            summary += f" Representative source items: {titles}."
        citations = self._citations(bundle)
        research_reports = self._research_reports(bundle, plan=plan)
        return DistilledSkill(
            id=stable_id(
                bundle.profile.id,
                "local",
                plan.id,
                ",".join(item.id for item in top_items),
            ),
            profile_id=bundle.profile.id,
            title=plan.skill_name_hint,
            version="0.1.0",
            summary=summary,
            principles=_principles_from_plan(plan, keywords),
            workflow=_workflow_from_plan(plan),
            style_rules=_style_rules_from_plan(plan),
            blindspots=plan.guardrails[:8],
            eval_cases=_eval_cases_from_plan(plan),
            citations=citations,
            metadata={
                "distiller": "local_fallback",
                "keywords": keywords,
                "item_count": len(bundle.items),
                "segment_count": len(bundle.segments),
                "comment_count": len(bundle.comments),
                "research_reports": research_reports,
                "focus": focus or "",
                "domain": plan.domain,
                "capability_type": plan.capability_type,
                "distillation_plan": plan.to_dict(),
            },
        )

    @staticmethod
    def _corpus(bundle: ProfileBundle, max_items: int, max_chars: int) -> str:
        segments_by_item: dict[str, list[Any]] = {}
        for segment in bundle.segments:
            segments_by_item.setdefault(segment.item_id, []).append(segment)
        lines: list[str] = [
            f"Profile: {bundle.profile.display_name or bundle.profile.handle}",
            f"Platform: {bundle.profile.platform}",
            f"URL: {bundle.profile.profile_url}",
        ]
        used = len("\n".join(lines))
        for index, item in enumerate(bundle.items[:max_items], start=1):
            text = truncate(item.text, 1500)
            segment_lines = []
            for segment in segments_by_item.get(item.id, [])[:10]:
                if segment.text and segment.text.strip() != item.text.strip():
                    segment_lines.append(
                        f"- {segment.source}/{segment.position}: {truncate(segment.text, 900)}"
                    )
            segments_text = "\n".join(segment_lines)
            block = (
                f"\n[{index}] title={item.title}\n"
                f"url={item.url}\n"
                f"published_at={item.published_at or ''}\n"
                f"text={text}\n"
                f"segments=\n{segments_text}\n"
            )
            if used + len(block) > max_chars:
                break
            lines.append(block)
            used += len(block)
        return "\n".join(lines)

    @staticmethod
    def _citations(bundle: ProfileBundle) -> list[Citation]:
        citations: list[Citation] = []
        for item in bundle.items[:20]:
            quote = truncate(item.text, 220)
            if not quote:
                quote = truncate(item.title, 220)
            citations.append(
                Citation(
                    source_url=item.url,
                    item_id=item.id,
                    quote=quote,
                    position=item.published_at,
                )
            )
        return citations

    @staticmethod
    def _keywords(text: str) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9_-]{2,}", text)
        stop = {
            "这个",
            "我们",
            "他们",
            "以及",
            "因为",
            "所以",
            "但是",
            "如果",
            "可以",
            "没有",
            "一个",
            "今天",
            "就是",
            "不是",
            "还是",
            "with",
            "from",
            "that",
            "this",
            "into",
        }
        counts = Counter(token for token in tokens if token.lower() not in stop)
        return [token for token, _ in counts.most_common(20)]

    @staticmethod
    def _research_reports(
        bundle: ProfileBundle,
        plan: DistillationPlan | None = None,
    ) -> list[dict[str, Any]]:
        segments_by_item: dict[str, list[str]] = {}
        for segment in bundle.segments:
            segments_by_item.setdefault(segment.item_id, []).append(segment.text)
        reports: list[dict[str, Any]] = []
        for item in bundle.items:
            evidence = "\n".join(segments_by_item.get(item.id, [])[:8]) or item.text
            keywords = Distiller._keywords(evidence)
            reports.append(
                {
                    "title": item.title,
                    "source_url": item.url,
                    "question": _infer_question(item.title, evidence, plan=plan),
                    "indicators": _infer_indicators(evidence, keywords, plan=plan),
                    "tools": _infer_tools(evidence, plan=plan),
                    "transmission_chain": _infer_chain(evidence, plan=plan),
                    "conclusion": truncate(evidence, 360),
                }
            )
        return reports

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise ValueError("model did not return a JSON object")


def _summary_from_plan(bundle: ProfileBundle, plan: DistillationPlan) -> str:
    profile_name = _profile_name(bundle)
    goal = f" for `{plan.goal}`" if plan.goal else ""
    return (
        f"{profile_name} {plan.capability_type} Skill is distilled from "
        f"{len(bundle.items)} public items, {len(bundle.segments)} text segments, "
        f"and {len(bundle.assets)} media assets{goal}. The planner classified the corpus as "
        f"`{plan.domain}` and produced a reusable extraction plan with confidence "
        f"{plan.confidence:.2f}. Local fallback output is a runnable skeleton; model-backed "
        "distillation can deepen the procedure while preserving the same plan."
    )


def _principles_from_plan(plan: DistillationPlan, keywords: list[str]) -> list[str]:
    topic_phrase = ", ".join(keywords[:8]) if keywords else ", ".join(plan.extraction_targets[:5])
    principles = [
        f"Extract only the reusable `{plan.capability_type}` behavior supported by source evidence.",
        f"Use the planner targets as the capability boundary: {', '.join(plan.extraction_targets[:8])}.",
        f"Treat high-frequency source themes as clues, not proof: {topic_phrase}.",
        "Separate source-observed facts, inferred procedure, and user-facing recommendation.",
        "Attach evidence or uncertainty labels to every strong rule.",
    ]
    return _dedupe([*principles, *plan.evidence_questions[:4]])[:12]


def _workflow_from_plan(plan: DistillationPlan) -> list[str]:
    workflow: list[str] = []
    for task in plan.tasks:
        questions = "; ".join(task.evidence_questions[:2])
        suffix = f" Evidence questions: {questions}." if questions else ""
        workflow.append(f"{task.title}: {task.purpose}.{suffix}")
    workflow.extend(
        [
            f"Structure the final answer around these axes: {', '.join(plan.workflow_axes)}.",
            "Before applying the Skill to a new case, state required inputs and missing evidence.",
            "After producing output, run guardrail checks and mark low-confidence steps.",
        ]
    )
    return _dedupe(workflow)[:12]


def _style_rules_from_plan(plan: DistillationPlan) -> list[str]:
    rules = [
        f"Write for {plan.audience}.",
        f"Use style constraints from the plan: {', '.join(plan.style_axes)}.",
        "Prefer concrete procedures over creator-personality imitation.",
        "Quote or cite source evidence when explaining where a rule came from.",
        "When evidence is thin, say what cannot be inferred.",
    ]
    return _dedupe(rules)[:12]


def _eval_cases_from_plan(plan: DistillationPlan) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for index, scenario in enumerate(plan.eval_scenarios[:6], 1):
        cases.append(
            {
                "name": f"{plan.domain} scenario {index}",
                "input": scenario,
                "expected_behavior": (
                    f"Apply the `{plan.capability_type}` workflow, cite relevant evidence, "
                    "state assumptions, and refuse unsupported inferences."
                ),
            }
        )
    if not cases:
        cases.append(
            {
                "name": "evidence constrained use",
                "input": "Apply this Skill to a new case with incomplete evidence.",
                "expected_behavior": "State assumptions, missing evidence, reusable steps, and limits.",
            }
        )
    return cases


def _bundle_text(bundle: ProfileBundle) -> str:
    parts: list[str] = []
    for item in bundle.items:
        parts.extend([item.title, item.text])
    for segment in bundle.segments:
        parts.append(segment.text)
    for comment in bundle.comments:
        parts.append(comment.text)
    return "\n".join(part for part in parts if part)


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _profile_name(bundle: ProfileBundle) -> str:
    return bundle.profile.display_name or bundle.profile.handle or bundle.profile.platform


def _as_eval_cases(value: Any) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    if not isinstance(value, list):
        return cases
    for item in value:
        if isinstance(item, dict):
            cases.append(
                {
                    "name": str(item.get("name") or "case"),
                    "input": str(item.get("input") or ""),
                    "expected_behavior": str(item.get("expected_behavior") or ""),
                }
            )
    return cases[:12]


def _as_research_reports(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    reports: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            reports.append(
                {
                    "title": str(item.get("title") or ""),
                    "source_url": str(item.get("source_url") or ""),
                    "question": str(item.get("question") or ""),
                    "indicators": _as_str_list(item.get("indicators")),
                    "tools": _as_str_list(item.get("tools")),
                    "transmission_chain": str(item.get("transmission_chain") or ""),
                    "conclusion": str(item.get("conclusion") or ""),
                }
            )
    return reports[:120]


def _merge_reports(
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for report in [*primary, *fallback]:
        key = str(report.get("source_url") or report.get("title") or len(merged))
        if key in seen:
            continue
        seen.add(key)
        merged.append(report)
    return merged


def _post_json(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(part.get("text", part)) for part in content)
    return json.dumps(data, ensure_ascii=False)


def _infer_question(
    title: str,
    evidence: str,
    *,
    plan: DistillationPlan | None = None,
) -> str:
    if plan and plan.evidence_questions:
        return plan.evidence_questions[0]
    if title.strip():
        return f"What reusable capability pattern is demonstrated by `{truncate(title, 80)}`?"
    if evidence.strip():
        return "What reusable capability pattern is demonstrated by this evidence?"
    return "What capability can be extracted from the source?"


def _infer_indicators(
    evidence: str,
    keywords: list[str],
    *,
    plan: DistillationPlan | None = None,
) -> list[str]:
    planned = plan.extraction_targets if plan else []
    visible = [item for item in planned if item.lower() in evidence.lower()]
    return _dedupe([*visible, *planned[:6], *keywords[:8]])[:12]


def _infer_tools(
    evidence: str,
    *,
    plan: DistillationPlan | None = None,
) -> list[str]:
    tools = list(plan.workflow_axes if plan else [])
    if re.search(r"\bjson\b|schema|表格|模板|清单|checklist", evidence, re.I):
        tools.append("structured template")
    if re.search(r"复盘|review|iteration|迭代", evidence, re.I):
        tools.append("review loop")
    if re.search(r"评论|comment|用户|audience", evidence, re.I):
        tools.append("audience feedback")
    return _dedupe(tools)[:10] or ["evidence review", "procedure extraction", "guardrail check"]


def _infer_chain(
    evidence: str,
    *,
    plan: DistillationPlan | None = None,
) -> str:
    if plan and plan.workflow_axes:
        return " -> ".join(plan.workflow_axes)
    return "source evidence -> repeated pattern -> reusable rule -> output -> guardrail check"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in result:
            result.append(clean)
    return result
