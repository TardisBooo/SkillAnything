"""Configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    home: Path
    rsshub_base: str
    openai_api_key: str | None
    model: str | None
    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str | None
    x_bearer_token: str | None
    cdp_url: str
    vision_api_key: str | None
    vision_base_url: str | None
    vision_model: str | None
    asr_api_key: str | None
    asr_base_url: str | None
    asr_model: str | None
    asr_language: str | None
    media_max_assets: int
    xueqiu_cookie: str | None = None

    @property
    def db_path(self) -> Path:
        return self.home / "skillanything.sqlite3"

    @property
    def archive_dir(self) -> Path:
        return self.home / "archive"

    @property
    def output_dir(self) -> Path:
        return self.home / "output"


def load_settings() -> Settings:
    """Load settings from environment with local-first defaults."""
    load_dotenv()
    home = Path(os.getenv("SKILLANYTHING_HOME", "./data")).expanduser().resolve()
    vision_base_url = os.getenv("SKILLANYTHING_VISION_BASE_URL") or None
    vision_api_key = (
        os.getenv("SKILLANYTHING_VISION_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("SILICONFLOW_API_KEY")
        or None
    )
    return Settings(
        home=home,
        rsshub_base=os.getenv("SKILLANYTHING_RSSHUB_BASE", "https://rsshub.app").rstrip("/"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        model=os.getenv("SKILLANYTHING_MODEL") or os.getenv("OPENAI_MODEL") or None,
        llm_api_key=os.getenv("SKILLANYTHING_LLM_API_KEY") or vision_api_key,
        llm_base_url=os.getenv("SKILLANYTHING_LLM_BASE_URL") or vision_base_url,
        llm_model=os.getenv("SKILLANYTHING_LLM_MODEL") or os.getenv("SKILLANYTHING_MODEL") or None,
        x_bearer_token=os.getenv("X_BEARER_TOKEN") or None,
        cdp_url=os.getenv("SKILLANYTHING_CDP_URL", "http://127.0.0.1:9222"),
        vision_api_key=vision_api_key,
        vision_base_url=vision_base_url,
        vision_model=os.getenv("SKILLANYTHING_VISION_MODEL") or None,
        asr_api_key=os.getenv("SKILLANYTHING_ASR_API_KEY") or vision_api_key,
        asr_base_url=os.getenv("SKILLANYTHING_ASR_BASE_URL") or vision_base_url,
        asr_model=os.getenv("SKILLANYTHING_ASR_MODEL") or None,
        asr_language=os.getenv("SKILLANYTHING_ASR_LANGUAGE") or None,
        media_max_assets=int(os.getenv("SKILLANYTHING_MEDIA_MAX_ASSETS", "80")),
        xueqiu_cookie=os.getenv("SKILLANYTHING_XUEQIU_COOKIE") or None,
    )
