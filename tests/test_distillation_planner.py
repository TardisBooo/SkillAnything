from __future__ import annotations

from pathlib import Path

from skillanything.config import Settings
from skillanything.distill.distiller import Distiller
from skillanything.distill.planner import DistillationPlanner
from skillanything.models import ContentItem, Profile, ProfileBundle


def test_planner_and_local_distiller_handle_trading_strategy(tmp_path: Path) -> None:
    bundle = _bundle(
        platform="stock-live",
        text=(
            "今天实盘复盘：早盘只做龙头分歧低吸，买入前先看板块强度、分时承接、"
            "成交量和大盘风险。仓位最多三成，跌破昨日低点止损，不做情绪退潮期的追高。"
            "收盘复盘每笔交易的入场理由、卖出触发、回撤和是否执行纪律。"
        ),
    )
    plan = DistillationPlanner().plan(
        bundle,
        goal="蒸馏股票交易实盘选手的策略 Skill",
        capability_type="trading_strategy",
    )
    assert plan.domain == "trading_strategy"
    assert "position sizing" in plan.extraction_targets

    skill = Distiller(_settings(tmp_path)).distill(
        bundle,
        focus="蒸馏股票交易实盘选手的策略 Skill",
        capability_type="trading_strategy",
    )
    assert skill.metadata["domain"] == "trading_strategy"
    assert skill.metadata["capability_type"] == "trading_strategy"
    assert "Macro Analysis" not in skill.title
    assert any("risk" in step.lower() or "止损" in step for step in skill.workflow)


def test_planner_and_local_distiller_handle_xiaohongshu_marketing(tmp_path: Path) -> None:
    bundle = _bundle(
        platform="xiaohongshu",
        text=(
            "小红书投放复盘：先用评论区找用户痛点，再设计封面和标题钩子。"
            "种草笔记要把场景、对比、使用前后变化和私信转化路径写清楚。"
            "达人素材看收藏率、评论关键词和进线成本，不只看曝光。"
        ),
    )
    plan = DistillationPlanner().plan(
        bundle,
        goal="提取小红书自媒体广告营销 Skill",
        capability_type="marketing_growth",
    )
    assert plan.domain == "marketing_growth"
    assert "hook" in plan.extraction_targets

    skill = Distiller(_settings(tmp_path)).distill(
        bundle,
        focus="提取小红书自媒体广告营销 Skill",
        capability_type="marketing_growth",
    )
    assert skill.metadata["domain"] == "marketing_growth"
    assert skill.metadata["capability_type"] == "marketing_growth"
    assert "Macro Analysis" not in skill.title
    assert any("audience" in item.lower() or "hook" in item.lower() for item in skill.principles)


def _bundle(platform: str, text: str) -> ProfileBundle:
    profile = Profile(
        id=f"profile-{platform}",
        platform=platform,
        profile_url=f"https://example.test/{platform}",
        display_name=f"{platform} creator",
    )
    item = ContentItem(
        id=f"item-{platform}",
        profile_id=profile.id,
        platform=platform,
        source_id="1",
        url=f"https://example.test/{platform}/1",
        title=f"{platform} notes",
        text=text,
    )
    return ProfileBundle(profile=profile, items=[item])


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
