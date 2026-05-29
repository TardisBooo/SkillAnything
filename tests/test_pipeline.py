from __future__ import annotations

from pathlib import Path

from skillanything.config import Settings
from skillanything.connectors.base import FetchRequest
from skillanything.connectors.xiaohongshu import XiaohongshuConnector
from skillanything.connectors.xueqiu import XueqiuConnector
from skillanything.pipeline import SkillAnythingApp


def test_file_to_skill_package(tmp_path: Path) -> None:
    source = tmp_path / "macro-notes.md"
    source.write_text(
        """
        # Macro notes

        降息会通过贴现率、风险偏好和流动性影响权益资产。
        如果盈利预期下修，宽松也可能无法推动指数持续上行。
        需要同时观察政策、信用、美元、商品和成交量。
        """,
        encoding="utf-8",
    )
    settings = Settings(
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
    app = SkillAnythingApp(settings)
    result = app.collect(str(source), platform="macro")
    assert len(result.items) == 1
    skill = app.distill(result.profile.id)
    assert skill.profile_id == result.profile.id
    output = app.export(skill.id)
    assert (output / "SKILL.md").exists()
    assert (output / "references" / "evidence.json").exists()


def test_xiaohongshu_initial_state_parser(monkeypatch) -> None:
    state = {
        "user": {
            "userPageData": {
                "basicInfo": {
                    "nickname": "Williams.Wang",
                    "redId": "9522431194",
                    "desc": "还没有简介",
                },
                "interactions": [{"name": "粉丝", "count": "1千+"}],
                "tags": [{"name": "上海虹口", "tagType": "location"}],
            },
            "notes": [
                [
                    {
                        "noteCard": {
                            "noteId": "abc123",
                            "xsecToken": "token",
                            "type": "normal",
                            "displayTitle": "社媒中的看空言论为何具有超额传播力",
                            "interactInfo": {"likedCount": "29", "sticky": True},
                            "cover": {
                                "urlDefault": "https://example.test/cover.webp",
                                "infoList": [{"url": "https://example.test/cover-small.webp"}],
                            },
                        }
                    }
                ]
            ],
        }
    }
    html = (
        "<html><script>window.__INITIAL_STATE__="
        + __import__("json").dumps(state, ensure_ascii=False)
        + "</script></html>"
    )
    monkeypatch.setattr(XiaohongshuConnector, "_fetch_html", staticmethod(lambda url: html))
    result = XiaohongshuConnector().collect(
        FetchRequest(
            source="https://www.xiaohongshu.com/user/profile/606c616d0000000001001124",
            platform="xiaohongshu",
        )
    )
    assert result.profile.display_name == "Williams.Wang"
    assert result.items[0].title == "社媒中的看空言论为何具有超额传播力"
    assert len(result.assets) == 2


def test_xueqiu_text_connector(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
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

    def fake_read_text(opener, url, headers, timeout=30):
        if "/u/2445021949" in url:
            return (
                '<html><script>SNOWMAN_USER = {"screen_name":"测试用户",'
                '"description":"雪球简介"};</script></html>'
            )
        return '<html><div class="article__bd">详情长文<br>风险传导链</div></html>'

    def fake_timeline(opener, headers, user_id, type_id, page):
        assert user_id == "2445021949"
        return {
            "total": 1,
            "maxPage": 1,
            "statuses": [
                {
                    "id": 367951812,
                    "user_id": 2445021949,
                    "title": "",
                    "created_at": 1766817510000,
                    "description": "首屏文本<br/>关于英伟达和工业富联",
                    "target": "/2445021949/367951812",
                    "fav_count": 3,
                    "retweet_count": 2,
                    "reply_count": 1,
                    "user": {"screen_name": "测试用户"},
                }
            ],
        }

    monkeypatch.setattr("skillanything.connectors.xueqiu._read_text", fake_read_text)
    monkeypatch.setattr("skillanything.connectors.xueqiu._fetch_timeline", fake_timeline)
    result = XueqiuConnector(settings).collect(
        FetchRequest(
            source="https://xueqiu.com/u/2445021949",
            platform="xueqiu",
            max_items=10,
            include_media=True,
        )
    )
    assert result.profile.display_name == "测试用户"
    assert len(result.items) == 1
    assert result.assets == []
    assert "详情长文" in result.items[0].text
    assert result.segments[0].source == "xueqiu:text"


def test_local_qa_and_focused_skill(tmp_path: Path) -> None:
    source = tmp_path / "risk-notes.md"
    source.write_text(
        """
        # 美股风险

        分析美股风险需要观察长端利率、信用利差、VIX、美元流动性和市场广度。
        如果 HY OAS 和 VIX 同时上行，说明风险可能从估值调整进入去杠杆。
        """,
        encoding="utf-8",
    )
    settings = Settings(
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
    app = SkillAnythingApp(settings)
    result = app.collect(str(source), platform="macro")
    answer = app.ask(result.profile.id, "如何分析美股风险？")
    assert "长端利率" in answer["answer"]
    assert answer["sources"]
    skill = app.extract_focused_skill(result.profile.id, "美股风险分析")
    assert "美股风险分析" in skill.title
    assert skill.metadata["focus"] == "美股风险分析"


def test_saved_provider_settings_are_loaded(tmp_path: Path) -> None:
    settings = Settings(
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
    app = SkillAnythingApp(settings)
    app.init()
    app.repo.save_app_settings(
        {
            "SKILLANYTHING_LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "SKILLANYTHING_LLM_API_KEY": "test-key",
            "SKILLANYTHING_LLM_MODEL": "qwen-plus",
        }
    )

    loaded = SkillAnythingApp()
    loaded.settings = settings
    loaded.repo = app.repo
    loaded.init()
    assert loaded.settings.llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert loaded.settings.llm_api_key == "test-key"
    assert loaded.settings.llm_model == "qwen-plus"
