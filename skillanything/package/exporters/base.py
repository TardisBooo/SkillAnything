"""Export SkillPack IR into directories suitable for different AI platforms."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from skillanything.models import ProfileBundle
from skillanything.package.writer import SkillPackageWriter
from skillanything.utils import ensure_dir, slugify, utc_now


SUPPORTED_TARGETS = {
    "codex-skill",
    "openai-skill",
    "claude-skill",
    "claude-project-bundle",
    "json-ir",
}


@dataclass(slots=True)
class SkillPackExportResult:
    target: str
    path: str
    files: list[str]
    created_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SkillPackExporter:
    def export(
        self,
        pack: dict[str, Any],
        output_root: Path,
        *,
        target: str = "codex-skill",
        bundle: ProfileBundle | None = None,
    ) -> SkillPackExportResult:
        target = target.strip().lower()
        if target not in SUPPORTED_TARGETS:
            raise ValueError(f"unsupported export target: {target}")
        output_root = ensure_dir(output_root)
        if target == "claude-project-bundle":
            path = self._write_claude_project(pack, output_root, bundle=bundle)
        elif target == "json-ir":
            path = self._write_json_ir(pack, output_root)
        else:
            path = self._write_skill_directory(pack, output_root, target=target, bundle=bundle)
        files = [
            str(file.relative_to(path))
            for file in path.rglob("*")
            if file.is_file()
        ]
        return SkillPackExportResult(
            target=target,
            path=str(path),
            files=sorted(files),
            created_at=utc_now(),
            metadata={
                "pack_id": pack.get("id"),
                "capability_id": pack.get("capability_id"),
                "skill_id": pack.get("skill_id"),
            },
        )

    def _write_skill_directory(
        self,
        pack: dict[str, Any],
        output_root: Path,
        *,
        target: str,
        bundle: ProfileBundle | None,
    ) -> Path:
        skill = dict(pack.get("skill_json") or {})
        path = SkillPackageWriter().write(skill, output_root, bundle=bundle)
        (path / "distilled_pack.json").write_text(
            json.dumps(pack, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (path / "TARGET.md").write_text(_target_notes(target, pack), encoding="utf-8")
        return path

    def _write_json_ir(self, pack: dict[str, Any], output_root: Path) -> Path:
        path = ensure_dir(output_root / f"{slugify(str(pack.get('title') or 'skill-pack'))}-ir")
        (path / "distilled_pack.json").write_text(
            json.dumps(pack, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _write_claude_project(
        self,
        pack: dict[str, Any],
        output_root: Path,
        *,
        bundle: ProfileBundle | None,
    ) -> Path:
        title = str(pack.get("title") or "SkillAnything Skill")
        path = ensure_dir(output_root / f"{slugify(title)}-claude-project")
        knowledge = ensure_dir(path / "knowledge")
        skill = dict(pack.get("skill_json") or {})
        temporary = SkillPackageWriter().write(skill, output_root / ".tmp-claude", bundle=bundle)
        for rel in [
            Path("SKILL.md"),
            Path("references") / "methodology.md",
            Path("references") / "research_reports.md",
            Path("references") / "evidence.json",
            Path("assets") / "evals.json",
        ]:
            src = temporary / rel
            if src.exists():
                dest = knowledge / rel.name
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        (path / "PROJECT_INSTRUCTIONS.md").write_text(
            _claude_project_instructions(pack),
            encoding="utf-8",
        )
        (path / "README_IMPORT.md").write_text(_claude_import_readme(pack), encoding="utf-8")
        (path / "distilled_pack.json").write_text(
            json.dumps(pack, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


def _target_notes(target: str, pack: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Export Target: {target}",
            "",
            f"- Pack: {pack.get('id', '')}",
            f"- Capability: {pack.get('capability_id', '')}",
            f"- Skill: {pack.get('skill_id', '')}",
            "",
            "Use `SKILL.md` as the primary instruction file and keep "
            "`distilled_pack.json` as the machine-readable source of truth.",
            "",
        ]
    )


def _claude_project_instructions(pack: dict[str, Any]) -> str:
    capability = pack.get("capability") or {}
    return "\n".join(
        [
            f"# {pack.get('title', 'SkillAnything Project')}",
            "",
            str(capability.get("summary") or ""),
            "",
            "Use the files in `knowledge/` as project knowledge. Treat evidence as "
            "supporting context, not as a license to impersonate the source creator.",
            "",
            "When answering, prefer a concise conclusion, reasoning chain, scenarios, "
            "evidence limits, and watchlist.",
            "",
        ]
    )


def _claude_import_readme(pack: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Claude Project Import",
            "",
            "1. Create or open a Claude Project.",
            "2. Add `PROJECT_INSTRUCTIONS.md` as the project instructions.",
            "3. Upload files from `knowledge/` as project knowledge.",
            "4. Keep `distilled_pack.json` for audit and later regeneration.",
            "",
            f"Pack id: `{pack.get('id', '')}`",
            "",
        ]
    )
