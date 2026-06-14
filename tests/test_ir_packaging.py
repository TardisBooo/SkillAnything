from __future__ import annotations

from pathlib import Path

from skillanything.config import Settings
from skillanything.pipeline import SkillAnythingApp


def test_ir_capability_pack_and_multi_target_exports(tmp_path: Path) -> None:
    source = tmp_path / "robot-chain.md"
    source.write_text(
        """
        # Humanoid robot supply chain

        A reusable chain analysis should split humanoid robots into sensors,
        reducers, servo motors, controllers, batteries, software, assembly,
        and downstream integrators. For China relevance, map each node to
        local listed companies, then mark evidence strength and missing links.
        """,
        encoding="utf-8",
    )
    app = SkillAnythingApp(_settings(tmp_path))
    result = app.collect(str(source), platform="research")

    corpus = app.build_corpus(
        result.profile.id,
        goal="Build a China A-share humanoid robot chain corpus",
    )
    assert corpus["metadata"]["counts"]["documents"] == 1

    capability = app.extract_capability(
        result.profile.id,
        focus="China A-share supply chain relevance mining",
        capability_type="chain_relevance_mining",
    )
    assert capability["type"] == "chain_relevance_mining"
    assert capability["evidence"]

    packs = app.repo.list_skill_packs(capability_id=capability["id"])
    assert len(packs) == 1
    assert packs[0]["capability_id"] == capability["id"]

    json_artifact = app.export_pack(packs[0]["id"], target="json-ir")
    json_path = Path(json_artifact["path"])
    assert (json_path / "distilled_pack.json").exists()

    claude_artifact = app.export_pack(packs[0]["id"], target="claude-project-bundle")
    claude_path = Path(claude_artifact["path"])
    assert (claude_path / "PROJECT_INSTRUCTIONS.md").exists()
    assert (claude_path / "knowledge" / "SKILL.md").exists()

    artifacts = app.repo.list_export_artifacts(pack_id=packs[0]["id"])
    assert {artifact["target"] for artifact in artifacts} >= {
        "json-ir",
        "claude-project-bundle",
    }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        home=tmp_path / "data",
        rsshub_base="https://rsshub.app",
        openai_api_key=None,
        model=None,
        llm_api_key=None,
        llm_base_url=None,
        llm_model=None,
        x_bearer_token=None,
        cdp_url="http://127.0.0.1:9222",
        vision_api_key=None,
        vision_base_url=None,
        vision_model=None,
        asr_api_key=None,
        asr_base_url=None,
        asr_model=None,
        asr_language=None,
        media_max_assets=80,
    )
