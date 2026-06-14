"""Command-line entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from skillanything.package.writer import lint_skill_package
from skillanything.pipeline import SkillAnythingApp

app = typer.Typer(help="Local-first profile-to-skill pipeline.")
console = Console()


@app.command()
def init() -> None:
    """Initialize local storage."""
    sa = SkillAnythingApp()
    sa.init()
    console.print(f"Initialized [bold]{sa.settings.home}[/bold]")


@app.command()
def collect(
    source: str = typer.Argument(
        ...,
        help="Profile URL, RSSHub route/URL, webpage, or local file.",
    ),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Platform hint."),
    max_items: int = typer.Option(50, "--max-items", "-n", min=1, max=500),
    comments: bool = typer.Option(False, "--comments", help="Collect comments when supported."),
    no_media: bool = typer.Option(False, "--no-media", help="Skip media asset discovery."),
    shallow: bool = typer.Option(False, "--shallow", help="Skip per-item detail pages."),
    media_max_assets: Optional[int] = typer.Option(
        None,
        "--media-max-assets",
        help="Override multimodal analysis asset limit for this run.",
    ),
) -> None:
    """Collect and normalize profile content."""
    sa = SkillAnythingApp()
    result = sa.collect(
        source=source,
        platform=platform,
        max_items=max_items,
        include_comments=comments,
        include_media=not no_media,
        deep=not shallow,
        media_max_assets=media_max_assets,
    )
    console.print(f"Profile: [bold]{result.profile.id}[/bold] ({result.profile.platform})")
    console.print(
        f"Saved {len(result.items)} items, {len(result.segments)} segments, "
        f"{len(result.assets)} assets, {len(result.comments)} comments"
    )
    if result.diagnostics:
        console.print("Diagnostics: " + "; ".join(result.diagnostics))


@app.command()
def profiles() -> None:
    """List collected profiles."""
    sa = SkillAnythingApp()
    sa.init()
    rows = sa.repo.list_profiles()
    table = Table("id", "platform", "display", "url", "updated")
    for profile in rows:
        table.add_row(
            profile.id,
            profile.platform,
            profile.display_name or profile.handle or "",
            profile.profile_url,
            profile.updated_at or "",
        )
    console.print(table)


@app.command()
def items(profile_id: str, limit: int = typer.Option(50, "--limit", "-n")) -> None:
    """List collected items for a profile."""
    sa = SkillAnythingApp()
    sa.init()
    rows = sa.repo.list_items(profile_id, limit=limit)
    table = Table("id", "published", "title", "url")
    for item in rows:
        table.add_row(item.id, item.published_at or "", item.title[:80], item.url)
    console.print(table)


@app.command()
def distill(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    item_limit: int = typer.Option(200, "--item-limit", "-n", min=1, max=1000),
    goal: str = typer.Option("", "--goal", help="Optional distillation goal for the planner."),
) -> None:
    """Distill a collected profile into a Skill model."""
    sa = SkillAnythingApp()
    skill = sa.distill(profile_id, item_limit=item_limit, goal=goal)
    console.print(f"Skill: [bold]{skill.id}[/bold]")
    console.print(skill.summary)
    console.print(f"Distiller: {skill.metadata.get('distiller')}")


@app.command("build-corpus")
def build_corpus(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    goal: str = typer.Option("", "--goal", help="Distillation goal."),
    item_limit: int = typer.Option(1000, "--item-limit", "-n", min=1, max=5000),
) -> None:
    """Build and save a normalized Corpus IR record."""
    sa = SkillAnythingApp()
    corpus = sa.build_corpus(profile_id, goal=goal, item_limit=item_limit)
    counts = corpus.get("metadata", {}).get("counts", {})
    console.print(f"Corpus: [bold]{corpus['id']}[/bold]")
    console.print(f"Documents: {counts.get('documents', 0)}")


@app.command("extract-capability")
def extract_capability(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    focus: str = typer.Argument(..., help="Capability focus to extract."),
    capability_type: str = typer.Option(
        "analysis_method",
        "--type",
        help="Custom capability type, e.g. research_pattern or prompt_recipe.",
    ),
    item_limit: int = typer.Option(80, "--item-limit", "-n", min=1, max=500),
) -> None:
    """Extract a typed Capability IR record from a profile."""
    sa = SkillAnythingApp()
    capability = sa.extract_capability(
        profile_id,
        focus=focus,
        capability_type=capability_type,
        item_limit=item_limit,
    )
    console.print(f"Capability: [bold]{capability['id']}[/bold]")
    console.print(capability.get("summary") or "")


@app.command("capabilities")
def capabilities(
    profile_id: Optional[str] = typer.Option(None, "--profile-id", help="Filter by profile."),
    corpus_id: Optional[str] = typer.Option(None, "--corpus-id", help="Filter by corpus."),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200),
) -> None:
    """List distilled capabilities."""
    sa = SkillAnythingApp()
    sa.init()
    table = Table("id", "profile", "type", "state", "confidence", "name")
    for row in sa.repo.list_capabilities(profile_id=profile_id, corpus_id=corpus_id, limit=limit):
        table.add_row(
            row["id"],
            row["profile_id"],
            row.get("type") or "",
            row.get("review_state") or "",
            f"{float(row.get('confidence') or 0):.2f}",
            row.get("name") or "",
        )
    console.print(table)


@app.command("create-pack")
def create_pack(
    capability_id: str = typer.Argument(..., help="Capability id."),
    target: list[str] = typer.Option(
        None,
        "--target",
        help="Target surface, repeatable: codex-skill/openai-skill/claude-skill.",
    ),
) -> None:
    """Create a SkillPack IR record from a capability."""
    sa = SkillAnythingApp()
    pack = sa.create_skill_pack(capability_id, target_surfaces=target or None)
    console.print(f"Pack: [bold]{pack['id']}[/bold]")


@app.command()
def skills() -> None:
    """List distilled skills."""
    sa = SkillAnythingApp()
    sa.init()
    table = Table("id", "profile", "title", "version", "output")
    for row in sa.repo.list_skills():
        table.add_row(
            row["id"],
            row["profile_id"],
            row["title"],
            row["version"],
            row.get("output_dir") or "",
        )
    console.print(table)


@app.command("archive-media")
def archive_media(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    kind: list[str] = typer.Option(
        None,
        "--kind",
        help="Restrict asset kind, repeatable: image/video/subtitle/audio.",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum assets to download."),
    force: bool = typer.Option(False, "--force", help="Re-download existing local files."),
    workers: int = typer.Option(12, "--workers", min=1, max=64, help="Concurrent downloads."),
) -> None:
    """Download collected media assets to the local archive."""
    sa = SkillAnythingApp()
    result = sa.archive_media(
        profile_id=profile_id,
        kinds=set(kind) if kind else None,
        limit=limit,
        force=force,
        workers=workers,
    )
    console.print(result.to_dict())


@app.command("extract-audio")
def extract_audio(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    force: bool = typer.Option(False, "--force", help="Re-extract existing audio assets."),
) -> None:
    """Extract audio tracks from downloaded video assets."""
    sa = SkillAnythingApp()
    result = sa.extract_audio(profile_id=profile_id, force=force)
    console.print(result.to_dict())


@app.command("analyze-media")
def analyze_media(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    item_id: Optional[str] = typer.Option(None, "--item-id", help="Restrict to one item id."),
    source_id: Optional[str] = typer.Option(
        None,
        "--source-id",
        help="Restrict to one platform source id, e.g. Xiaohongshu note id.",
    ),
    kind: list[str] = typer.Option(
        None,
        "--kind",
        help="Restrict asset kind, repeatable: image/video/audio.",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum pending assets to analyze."),
    force: bool = typer.Option(False, "--force", help="Re-analyze assets with existing results."),
    workers: int = typer.Option(1, "--workers", min=1, max=16, help="Concurrent model calls."),
) -> None:
    """Run OCR/vision/ASR for archived media assets with asset-level caching."""
    sa = SkillAnythingApp()
    result = sa.analyze_media(
        profile_id=profile_id,
        item_id=item_id,
        source_id=source_id,
        kinds=set(kind) if kind else None,
        limit=limit,
        force=force,
        workers=workers,
    )
    console.print(result.to_dict())


@app.command()
def export(
    skill_id: str = typer.Argument(..., help="Distilled skill id."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output root directory."),
    target: str = typer.Option("codex-skill", "--target", help="Export target."),
) -> None:
    """Export a Skill package."""
    sa = SkillAnythingApp()
    path = sa.export(skill_id, output_root=output, target=target)
    console.print(f"Exported [bold]{skill_id}[/bold] to [bold]{path}[/bold]")


@app.command("export-pack")
def export_pack(
    pack_id: str = typer.Argument(..., help="SkillPack id."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output root directory."),
    target: str = typer.Option("codex-skill", "--target", help="Export target."),
) -> None:
    """Export a SkillPack to a target platform directory."""
    sa = SkillAnythingApp()
    artifact = sa.export_pack(pack_id, output_root=output, target=target)
    console.print(f"Exported [bold]{pack_id}[/bold] to [bold]{artifact['path']}[/bold]")


@app.command()
def ask(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    question: str = typer.Argument(..., help="Question to ask against the local knowledge base."),
    limit: int = typer.Option(8, "--limit", "-n", min=1, max=30),
) -> None:
    """Ask questions against a collected profile knowledge base."""
    sa = SkillAnythingApp()
    answer = sa.ask(profile_id, question, limit=limit)
    console.print(answer["answer"])
    if answer.get("sources"):
        table = Table("kind", "title", "url")
        for source in answer["sources"]:
            table.add_row(
                str(source.get("kind") or ""),
                str(source.get("title") or "")[:80],
                str(source.get("url") or ""),
            )
        console.print(table)


@app.command("extract-skill")
def extract_skill(
    profile_id: str = typer.Argument(..., help="Collected profile id."),
    focus: str = typer.Argument(..., help="Focused topic, e.g. 美股风险分析."),
    item_limit: int = typer.Option(80, "--item-limit", "-n", min=1, max=300),
) -> None:
    """Extract a focused Skill from a collected profile."""
    sa = SkillAnythingApp()
    skill = sa.extract_focused_skill(profile_id, focus=focus, item_limit=item_limit)
    console.print(f"Skill: [bold]{skill.id}[/bold]")
    console.print(skill.summary)


@app.command()
def lint(path: Path = typer.Argument(..., help="Skill package directory.")) -> None:
    """Lint an exported Skill package."""
    problems = lint_skill_package(path)
    if problems:
        for problem in problems:
            console.print(f"[red]error[/red] {problem}")
        raise typer.Exit(1)
    console.print("[green]ok[/green]")


@app.command()
def ui(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the local API server."""
    import uvicorn

    sa = SkillAnythingApp()
    sa.init()
    console.print(f"Starting local API at http://{host}:{port}")
    uvicorn.run("skillanything.web:api", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
