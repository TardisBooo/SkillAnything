"""Distill normalized profile evidence into an agent-ready skill model."""

from __future__ import annotations

import json
import re
import urllib.request
from collections import Counter
from typing import Any

from skillanything.config import Settings
from skillanything.models import Citation, DistilledSkill, ProfileBundle
from skillanything.utils import stable_id, truncate


class Distiller:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def distill(self, bundle: ProfileBundle, focus: str | None = None) -> DistilledSkill:
        if self.settings.llm_api_key and self.settings.llm_base_url:
            try:
                return self._distill_with_compatible_chat(bundle, focus=focus)
            except Exception as exc:
                fallback = self._distill_locally(bundle, focus=focus)
                fallback.metadata["model_error"] = f"{type(exc).__name__}: {exc}"
                return fallback
        if self.settings.openai_api_key:
            try:
                return self._distill_with_openai(bundle, focus=focus)
            except Exception as exc:
                fallback = self._distill_locally(bundle, focus=focus)
                fallback.metadata["model_error"] = f"{type(exc).__name__}: {exc}"
                return fallback
        return self._distill_locally(bundle, focus=focus)

    def _distill_with_compatible_chat(
        self,
        bundle: ProfileBundle,
        focus: str | None = None,
    ) -> DistilledSkill:
        model = self.settings.llm_model or self.settings.model or "qwen3-vl-plus"
        corpus = self._corpus(bundle, max_items=80, max_chars=60000)
        prompt = self._distill_prompt(corpus, focus=focus)
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
        )

    def _distill_with_openai(
        self,
        bundle: ProfileBundle,
        focus: str | None = None,
    ) -> DistilledSkill:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        model = self.settings.model or "gpt-5-mini"
        corpus = self._corpus(bundle, max_items=40, max_chars=30000)
        prompt = self._distill_prompt(corpus, focus=focus)
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
        )

    def _skill_from_model_data(
        self,
        bundle: ProfileBundle,
        data: dict[str, Any],
        distiller: str,
        model: str,
        focus: str | None = None,
    ) -> DistilledSkill:
        citations = self._citations(bundle)
        model_reports = _as_research_reports(data.get("research_reports"))
        local_reports = self._research_reports(bundle)
        research_reports = _merge_reports(model_reports, local_reports)
        title_focus = f" {focus.strip()}" if focus and focus.strip() else ""
        return DistilledSkill(
            id=stable_id(bundle.profile.id, "skill", focus or "", data.get("summary", "")),
            profile_id=bundle.profile.id,
            title=f"{_profile_name(bundle)}{title_focus} Skill",
            version="0.1.0",
            summary=str(data.get("summary") or "Profile-derived analysis skill."),
            principles=_as_str_list(data.get("principles"))[:12],
            workflow=_as_str_list(data.get("workflow"))[:12],
            style_rules=_as_str_list(data.get("style_rules"))[:12],
            blindspots=_as_str_list(data.get("blindspots"))[:12],
            eval_cases=_as_eval_cases(data.get("eval_cases")),
            citations=citations,
            metadata={
                "distiller": distiller,
                "model": model,
                "item_count": len(bundle.items),
                "segment_count": len(bundle.segments),
                "comment_count": len(bundle.comments),
                "research_reports": research_reports,
                "focus": focus or "",
            },
        )

    @staticmethod
    def _distill_prompt(corpus: str, focus: str | None = None) -> str:
        focus_line = (
            f"本次只围绕这个主题提取可复用 Skill：{focus.strip()}。\n"
            if focus and focus.strip()
            else ""
        )
        return (
            "你是一个研究型 AI Skill 架构师。基于以下公开内容证据，蒸馏出一个可供 "
            "agent 调用的分析 Skill。不要冒充作者本人，只提炼方法论、信息源偏好、"
            "推理流程、表达规则和盲区。先逐条内容归纳研究主题、核心问题、指标、"
            "工具、数据传导链和结论，再抽象成稳定方法论。\n"
            f"{focus_line}"
            "必须只输出 JSON 对象，不要输出 Markdown。字段如下："
            "summary, principles, workflow, style_rules, blindspots, "
            "research_reports, eval_cases。\n"
            "principles/workflow/style_rules/blindspots 都是字符串数组。"
            "research_reports 是数组，每项包含 title, source_url, question, "
            "indicators, tools, transmission_chain, conclusion。"
            "eval_cases 是数组，每项包含 name, input, expected_behavior。\n\n"
            f"证据语料：\n{corpus}"
        )

    def _distill_locally(
        self,
        bundle: ProfileBundle,
        focus: str | None = None,
    ) -> DistilledSkill:
        corpus_text = "\n".join(item.text for item in bundle.items if item.text)
        keywords = self._keywords(corpus_text)
        top_items = bundle.items[: min(8, len(bundle.items))]
        profile_name = _profile_name(bundle)
        focus_phrase = f"围绕“{focus}”" if focus else ""
        summary = (
            f"{profile_name} 的 Skill 由 {len(bundle.items)} 条内容、"
            f"{len(bundle.segments)} 个文本片段和 {len(bundle.assets)} 个媒体资产蒸馏而来。"
            f"{focus_phrase}本地 fallback 无法替代云模型深度理解，但可提供可运行的 Skill 包骨架。"
        )
        topic_phrase = "、".join(keywords[:6]) if keywords else "宏观、市场、风险、政策、估值"
        principles = [
            f"围绕高频主题建立分析框架：{topic_phrase}。",
            "优先把观点拆成事实、推理、结论和风险提示四段。",
            "保留原始证据引用，不把单条内容泛化为稳定规律。",
            "遇到市场预测时同时输出基准情景、乐观情景和风险情景。",
            "对强结论标注证据强度和可能失效条件。",
        ]
        workflow = [
            "读取用户问题并识别资产类别、时间尺度和宏观变量。",
            "检索 references/evidence.json 中的相似内容和引用片段。",
            "抽取相关事实、政策变量、资金变量、情绪变量和价格变量。",
            "按因果链组织推理，区分已发生事实和主观判断。",
            "输出结论、关键监测指标、反证条件和后续观察清单。",
        ]
        style_rules = [
            "表达保持研究员口吻，避免绝对化预测。",
            "重要判断后给出证据来源或说明证据不足。",
            "使用项目符号输出多情景分析，便于快速扫描。",
            "不声称自己就是原作者，不复制原作者身份或私密经历。",
        ]
        blindspots = [
            "公开主页内容可能存在幸存者偏差和删改缺口。",
            "短帖和评论更容易受市场情绪影响，不能单独作为方法论证据。",
            "缺少付费内容、私域社群或实时交易记录时，不推断其完整投资体系。",
            "音视频自动转写可能产生错字，需要对关键数字和专有名词回听核验。",
        ]
        eval_cases = [
            {
                "name": "宏观观点拆解",
                "input": "请按该 Skill 的方式分析一次降息对权益市场的影响。",
                "expected_behavior": "输出事实、传导链、受益/受损资产、风险情景和证据不足说明。",
            },
            {
                "name": "证据约束",
                "input": "这个分析师是否一定看多某个行业？",
                "expected_behavior": "拒绝无证据的绝对归因，引用已有内容并说明置信度。",
            },
            {
                "name": "反证条件",
                "input": "如果当前判断失败，应该观察哪些反证信号？",
                "expected_behavior": "列出政策、价格、成交、盈利和情绪方面的失效条件。",
            },
        ]
        citations = self._citations(bundle)
        research_reports = self._research_reports(bundle)
        if top_items:
            titles = "; ".join(truncate(item.title, 40) for item in top_items[:3])
            summary += f" 代表内容包括：{titles}。"
        return DistilledSkill(
            id=stable_id(
                bundle.profile.id,
                "local",
                focus or "",
                ",".join(item.id for item in top_items),
            ),
            profile_id=bundle.profile.id,
            title=f"{profile_name} {focus or 'Macro Analysis'} Skill",
            version="0.1.0",
            summary=summary,
            principles=principles,
            workflow=workflow,
            style_rules=style_rules,
            blindspots=blindspots,
            eval_cases=eval_cases,
            citations=citations,
            metadata={
                "distiller": "local_fallback",
                "keywords": keywords,
                "item_count": len(bundle.items),
                "segment_count": len(bundle.segments),
                "comment_count": len(bundle.comments),
                "research_reports": research_reports,
                "focus": focus or "",
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
            "市场",
            "今天",
            "就是",
            "不是",
            "还是",
        }
        counts = Counter(token for token in tokens if token not in stop)
        return [token for token, _ in counts.most_common(20)]

    @staticmethod
    def _research_reports(bundle: ProfileBundle) -> list[dict[str, Any]]:
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
                    "question": _infer_question(item.title, evidence),
                    "indicators": _infer_indicators(evidence, keywords),
                    "tools": _infer_tools(evidence),
                    "transmission_chain": _infer_chain(evidence),
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


def _infer_question(title: str, evidence: str) -> str:
    if "传导链" in title or "传导" in evidence:
        return "多重宏观/市场数据如何通过传导链影响资产价格与交易准备？"
    if "看空" in title:
        return "为什么看空观点更容易获得传播，如何校正情绪偏差？"
    if "利率" in title:
        return "利率期限结构如何映射增长、通胀、流动性和资产定价？"
    if "HBM" in title or "CPU" in title or "DRAM" in title:
        return "半导体产业数据如何影响供需、竞争格局和估值判断？"
    return f"如何分析：{truncate(title, 80)}"


def _infer_indicators(evidence: str, keywords: list[str]) -> list[str]:
    candidates = [
        "利率",
        "期限结构",
        "通胀",
        "就业",
        "美元",
        "流动性",
        "成交量",
        "波动率",
        "期权",
        "标普",
        "盈利预期",
        "库存",
        "DRAM",
        "NAND",
        "HBM",
        "CPU",
    ]
    found = [item for item in candidates if item.lower() in evidence.lower()]
    return list(dict.fromkeys(found + keywords[:8]))[:12]


def _infer_tools(evidence: str) -> list[str]:
    tools = []
    for candidate in ["option", "期权", "量化", "回测", "期限结构", "数据看板", "产业链图谱"]:
        if candidate.lower() in evidence.lower():
            tools.append(candidate)
    return tools or ["多指标交叉验证", "情景分析", "反证条件检查"]


def _infer_chain(evidence: str) -> str:
    if "传导链" in evidence:
        return "先定位数据变量，再判断变量方向，经由政策/流动性/盈利/风险偏好传导到资产价格。"
    if "利率" in evidence:
        return "利率与期限结构影响贴现率和风险偏好，再传导到权益估值、风格和仓位。"
    if "期权" in evidence or "option" in evidence.lower():
        return "期权定价、波动率和仓位结构反映市场预期，再反向影响短期价格路径。"
    return "事实数据 -> 变量关系 -> 市场机制 -> 情景结论 -> 反证条件。"
