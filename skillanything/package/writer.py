"""Write distilled skills to an agent-compatible directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skillanything.models import ProfileBundle
from skillanything.utils import ensure_dir, slugify


class SkillPackageWriter:
    def write(
        self,
        skill: dict[str, Any],
        output_root: Path,
        bundle: ProfileBundle | None = None,
    ) -> Path:
        title = str(skill.get("title") or "SkillAnything Skill")
        slug = slugify(title)
        skill_dir = ensure_dir(output_root / slug)
        posts_dir = ensure_dir(skill_dir / "posts")
        analysis_dir = ensure_dir(skill_dir / "分析")
        analysis_en_dir = ensure_dir(skill_dir / "analysis")
        ensure_dir(skill_dir / "references")
        ensure_dir(skill_dir / "assets")
        ensure_dir(skill_dir / "scripts")

        if bundle:
            (skill_dir / "name.md").write_text(self._name_md(bundle, skill), encoding="utf-8")
            self._write_posts(posts_dir, bundle)
            self._write_analysis(analysis_dir, bundle, skill)
            self._write_analysis(analysis_en_dir, bundle, skill)
            (skill_dir / "posts.json").write_text(
                json.dumps(_bundle_posts(bundle), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        (skill_dir / "SKILL.md").write_text(self._skill_md(skill), encoding="utf-8")
        (skill_dir / "skill.yaml").write_text(
            json.dumps(skill, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (skill_dir / "references" / "methodology.md").write_text(
            self._methodology_md(skill),
            encoding="utf-8",
        )
        (skill_dir / "references" / "research_reports.md").write_text(
            self._research_reports_md(skill),
            encoding="utf-8",
        )
        (skill_dir / "references" / "evidence.json").write_text(
            json.dumps(skill.get("citations", []), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (skill_dir / "assets" / "evals.json").write_text(
            json.dumps(skill.get("eval_cases", []), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (skill_dir / "scripts" / "run_eval.py").write_text(_EVAL_RUNNER, encoding="utf-8")
        return skill_dir

    @staticmethod
    def _name_md(bundle: ProfileBundle, skill: dict[str, Any]) -> str:
        profile = bundle.profile
        lines = [
            "# name",
            "",
            f"- Name: {profile.display_name or profile.handle or profile.id}",
            f"- Platform: {profile.platform}",
            f"- Profile URL: {profile.profile_url}",
            f"- Handle: {profile.handle or ''}",
            f"- Description: {profile.description or ''}",
            f"- Skill: {skill.get('title', '')}",
            f"- Posts: {len(bundle.items)}",
            f"- Media assets: {len(bundle.assets)}",
            f"- Text segments: {len(bundle.segments)}",
            "",
            "## Summary",
            "",
            str(skill.get("summary", "")),
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _write_posts(posts_dir: Path, bundle: ProfileBundle) -> None:
        assets_by_item = _group_by_item(bundle.assets)
        segments_by_item = _group_by_item(bundle.segments)
        comments_by_item = _group_by_item(bundle.comments)
        for index, item in enumerate(bundle.items, 1):
            path = posts_dir / f"post-{index:03d}-{slugify(item.title, item.id)}.md"
            lines = [
                f"# post{index}: {item.title}",
                "",
                f"- ID: {item.id}",
                f"- Source ID: {item.source_id or ''}",
                f"- URL: {item.url}",
                f"- Platform: {item.platform}",
                f"- Author: {item.author or ''}",
                f"- Published at: {item.published_at or ''}",
                f"- Metrics: `{json.dumps(item.metrics, ensure_ascii=False)}`",
                "",
                "## 文本",
                "",
                item.text or "",
                "",
                "## 媒体记录",
                "",
            ]
            for asset in assets_by_item.get(item.id, []):
                lines.extend(
                    [
                        f"### {asset.kind}: {asset.id}",
                        "",
                        f"- URL: {asset.url or ''}",
                        f"- Local path: {asset.local_path or ''}",
                        f"- MIME: {asset.mime_type or ''}",
                        f"- Metadata: `{json.dumps(asset.metadata, ensure_ascii=False)}`",
                        "",
                    ]
                )
            lines.extend(["## 多模态/字幕/语音提取", ""])
            for segment in segments_by_item.get(item.id, []):
                lines.extend(
                    [
                        f"### {segment.source} / {segment.position}",
                        "",
                        segment.text,
                        "",
                    ]
                )
            lines.extend(["## 评论", ""])
            for comment in comments_by_item.get(item.id, []):
                lines.extend(
                    [
                        f"- {comment.author or ''} {comment.published_at or ''}: {comment.text}",
                    ]
                )
            path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _write_analysis(analysis_dir: Path, bundle: ProfileBundle, skill: dict[str, Any]) -> None:
        reports = skill.get("metadata", {}).get("research_reports", [])
        report_by_url = {report.get("source_url"): report for report in reports}
        report_by_title = {report.get("title"): report for report in reports}
        for index, item in enumerate(bundle.items, 1):
            report = report_by_url.get(item.url) or report_by_title.get(item.title) or {}
            path = analysis_dir / f"post-{index:03d}-{slugify(item.title, item.id)}.md"
            lines = [
                f"# post{index} 分析：{item.title}",
                "",
                f"- Source: {item.url}",
                f"- Question: {report.get('question', '')}",
                f"- Indicators: {', '.join(report.get('indicators', []))}",
                f"- Tools: {', '.join(report.get('tools', []))}",
                f"- Transmission Chain: {report.get('transmission_chain', '')}",
                "",
                "## 总结",
                "",
                str(report.get("conclusion") or item.text or ""),
                "",
            ]
            path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _skill_md(skill: dict[str, Any]) -> str:
        name = slugify(str(skill.get("title") or "distilled-skill"))
        description = (
            "Use this skill to apply a distilled public-content analysis framework while "
            "citing source evidence and avoiding impersonation."
        )
        lines = [
            "---",
            f"name: {name}",
            f"description: {description}",
            "---",
            "",
            f"# {skill.get('title', 'Distilled Skill')}",
            "",
            "## Purpose",
            "",
            str(skill.get("summary", "")),
            "",
            "This skill extracts reusable analysis habits from public material. It must not "
            "claim to be,",
            "represent, or impersonate the original creator.",
            "",
            "## Operating Principles",
            "",
        ]
        lines.extend(f"- {item}" for item in skill.get("principles", []))
        lines.extend(["", "## Workflow", ""])
        lines.extend(
            f"{index}. {_strip_numbering(item)}"
            for index, item in enumerate(skill.get("workflow", []), 1)
        )
        lines.extend(["", "## Style Rules", ""])
        lines.extend(f"- {item}" for item in skill.get("style_rules", []))
        lines.extend(["", "## Blind Spots And Guardrails", ""])
        lines.extend(f"- {item}" for item in skill.get("blindspots", []))
        lines.extend(
            [
                "",
                "## Evidence Policy",
                "",
                "- Prefer citations from `references/evidence.json` when making claims "
                "about the source profile.",
                "- Mark low-confidence conclusions explicitly.",
                "- Do not invent private beliefs, trades, positions, credentials, or "
                "unpublished sources.",
                "",
                "## Output Template",
                "",
                "```markdown",
                "## Conclusion",
                "<short answer>",
                "",
                "## Reasoning Chain",
                "- Fact:",
                "- Mechanism:",
                "- Implication:",
                "",
                "## Scenarios",
                "- Base:",
                "- Upside:",
                "- Downside:",
                "",
                "## Evidence",
                "- <source citation or limitation>",
                "",
                "## Watchlist",
                "- <signals that would confirm or falsify the view>",
                "```",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _methodology_md(skill: dict[str, Any]) -> str:
        lines = [
            f"# {skill.get('title', 'Distilled Skill')} Methodology",
            "",
            "## Summary",
            "",
            str(skill.get("summary", "")),
            "",
            "## Principles",
            "",
        ]
        lines.extend(f"- {item}" for item in skill.get("principles", []))
        lines.extend(["", "## Workflow", ""])
        lines.extend(
            f"{index}. {_strip_numbering(item)}"
            for index, item in enumerate(skill.get("workflow", []), 1)
        )
        lines.extend(["", "## Metadata", "", "```json"])
        lines.append(json.dumps(skill.get("metadata", {}), ensure_ascii=False, indent=2))
        lines.extend(["```", ""])
        return "\n".join(lines)

    @staticmethod
    def _research_reports_md(skill: dict[str, Any]) -> str:
        reports = skill.get("metadata", {}).get("research_reports", [])
        lines = ["# Research Reports", ""]
        if not reports:
            lines.append("No per-item research reports were generated.")
            return "\n".join(lines)
        for index, report in enumerate(reports, 1):
            lines.extend(
                [
                    f"## {index}. {report.get('title', 'Untitled')}",
                    "",
                    f"- Source: {report.get('source_url', '')}",
                    f"- Question: {report.get('question', '')}",
                    f"- Indicators: {', '.join(report.get('indicators', []))}",
                    f"- Tools: {', '.join(report.get('tools', []))}",
                    f"- Transmission Chain: {report.get('transmission_chain', '')}",
                    "",
                    str(report.get("conclusion", "")),
                    "",
                ]
            )
        return "\n".join(lines)


def lint_skill_package(path: Path) -> list[str]:
    problems: list[str] = []
    required = [
        path / "name.md",
        path / "posts.json",
        path / "SKILL.md",
        path / "skill.yaml",
        path / "references" / "methodology.md",
        path / "references" / "research_reports.md",
        path / "references" / "evidence.json",
        path / "assets" / "evals.json",
    ]
    for file_path in required:
        if not file_path.exists():
            problems.append(f"missing {file_path.relative_to(path)}")
    if (path / "SKILL.md").exists():
        text = (path / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        if "Evidence Policy" not in text:
            problems.append("SKILL.md missing Evidence Policy section")
        if "impersonate" not in text:
            problems.append("SKILL.md missing impersonation guardrail")
    return problems


def _group_by_item(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.item_id, []).append(row)
    return grouped


def _bundle_posts(bundle: ProfileBundle) -> list[dict[str, Any]]:
    assets_by_item = _group_by_item(bundle.assets)
    segments_by_item = _group_by_item(bundle.segments)
    comments_by_item = _group_by_item(bundle.comments)
    posts: list[dict[str, Any]] = []
    for item in bundle.items:
        posts.append(
            {
                "item": item.to_dict(),
                "assets": [asset.to_dict() for asset in assets_by_item.get(item.id, [])],
                "segments": [segment.to_dict() for segment in segments_by_item.get(item.id, [])],
                "comments": [comment.to_dict() for comment in comments_by_item.get(item.id, [])],
            }
        )
    return posts


def _strip_numbering(value: Any) -> str:
    import re

    text = str(value).strip()
    return re.sub(r"^\s*\d+[\.\)、)]\s*", "", text)


_EVAL_RUNNER = '''"""Minimal eval smoke runner for a generated Skill package."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    evals = json.loads((root / "assets" / "evals.json").read_text(encoding="utf-8"))
    print(f"Loaded {len(evals)} eval cases from {root}")
    for index, case in enumerate(evals, 1):
        print(f"{index}. {case.get('name', 'case')}: {case.get('input', '')[:120]}")


if __name__ == "__main__":
    main()
'''
