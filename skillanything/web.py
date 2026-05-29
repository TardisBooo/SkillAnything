"""Local FastAPI API."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from skillanything.pipeline import SkillAnythingApp

api = FastAPI(title="SkillAnything Local", version="0.1.0")
_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2)


class CollectRequest(BaseModel):
    source: str
    platform: Optional[str] = None
    max_items: int = Field(default=50, ge=1, le=500)
    include_comments: bool = False
    include_media: bool = True
    deep: bool = True
    media_max_assets: Optional[int] = Field(default=None, ge=0, le=1000)


class DistillRequest(BaseModel):
    item_limit: int = Field(default=200, ge=1, le=1000)


class ExportRequest(BaseModel):
    output_root: Optional[str] = None


class ArchiveMediaRequest(BaseModel):
    kinds: Optional[list[str]] = None
    limit: Optional[int] = Field(default=None, ge=1)
    force: bool = False
    workers: int = Field(default=12, ge=1, le=64)


class ProfileFullRunRequest(BaseModel):
    source: str
    platform: Optional[str] = None
    max_items: int = Field(default=50, ge=1, le=1000)
    include_comments: bool = False
    include_media: bool = True
    deep: bool = True
    media_max_assets: Optional[int] = Field(default=None, ge=0, le=5000)
    item_limit: int = Field(default=200, ge=1, le=1000)


class AskRequest(BaseModel):
    question: str
    limit: int = Field(default=8, ge=1, le=30)


class FocusSkillRequest(BaseModel):
    focus: str
    item_limit: int = Field(default=80, ge=1, le=300)


class ProviderSettingsRequest(BaseModel):
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    vision_base_url: Optional[str] = None
    vision_api_key: Optional[str] = None
    vision_model: Optional[str] = None
    asr_base_url: Optional[str] = None
    asr_api_key: Optional[str] = None
    asr_model: Optional[str] = None
    asr_language: Optional[str] = None
    xueqiu_cookie: Optional[str] = None
    cdp_url: Optional[str] = None
    media_max_assets: Optional[int] = Field(default=None, ge=0, le=5000)


@api.on_event("startup")
def _startup() -> None:
    SkillAnythingApp().init()


@api.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


@api.get("/health")
def health() -> dict:
    sa = SkillAnythingApp()
    return {
        "ok": True,
        "home": str(sa.settings.home),
        "db": str(sa.settings.db_path),
    }


@api.get("/config/status")
def config_status() -> dict:
    sa = SkillAnythingApp()
    sa.init()
    return {
        "home": str(sa.settings.home),
        "db": str(sa.settings.db_path),
        "llm_configured": bool(sa.settings.llm_api_key and sa.settings.llm_base_url),
        "vision_configured": bool(sa.settings.vision_api_key and sa.settings.vision_base_url),
        "asr_configured": bool(sa.settings.asr_api_key and sa.settings.asr_base_url),
        "xueqiu_cookie_configured": bool(sa.settings.xueqiu_cookie),
        "cdp_url": sa.settings.cdp_url,
    }


@api.get("/settings")
def get_settings() -> dict:
    sa = SkillAnythingApp()
    sa.init()
    return _settings_response(sa)


@api.post("/settings")
def save_settings(request: ProviderSettingsRequest) -> dict:
    sa = SkillAnythingApp()
    sa.init()
    values: dict[str, str] = {}
    mapping = {
        "llm_base_url": "SKILLANYTHING_LLM_BASE_URL",
        "llm_api_key": "SKILLANYTHING_LLM_API_KEY",
        "llm_model": "SKILLANYTHING_LLM_MODEL",
        "vision_base_url": "SKILLANYTHING_VISION_BASE_URL",
        "vision_api_key": "SKILLANYTHING_VISION_API_KEY",
        "vision_model": "SKILLANYTHING_VISION_MODEL",
        "asr_base_url": "SKILLANYTHING_ASR_BASE_URL",
        "asr_api_key": "SKILLANYTHING_ASR_API_KEY",
        "asr_model": "SKILLANYTHING_ASR_MODEL",
        "asr_language": "SKILLANYTHING_ASR_LANGUAGE",
        "xueqiu_cookie": "SKILLANYTHING_XUEQIU_COOKIE",
        "cdp_url": "SKILLANYTHING_CDP_URL",
        "media_max_assets": "SKILLANYTHING_MEDIA_MAX_ASSETS",
    }
    for field, key in mapping.items():
        value = getattr(request, field)
        if value is not None:
            values[key] = str(value).strip()
    sa.repo.save_app_settings(values)
    sa = SkillAnythingApp()
    sa.init()
    return _settings_response(sa)


@api.get("/profiles")
def profiles() -> list[dict]:
    sa = SkillAnythingApp()
    sa.init()
    return [profile.to_dict() for profile in sa.repo.list_profiles()]


@api.get("/profiles/{profile_id}/items")
def profile_items(profile_id: str, limit: int = 100) -> list[dict]:
    sa = SkillAnythingApp()
    sa.init()
    return [item.to_dict() for item in sa.repo.list_items(profile_id, limit=limit)]


@api.get("/jobs")
def jobs(limit: int = 50) -> list[dict]:
    sa = SkillAnythingApp()
    sa.init()
    return sa.repo.list_jobs(limit=limit)


@api.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    sa = SkillAnythingApp()
    sa.init()
    row = sa.repo.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return row


@api.post("/jobs/profile-full-run")
def profile_full_run_job(request: ProfileFullRunRequest) -> dict:
    payload = request.model_dump()

    def runner(
        sa: SkillAnythingApp,
        progress: Callable[[int, dict[str, Any] | None], None],
    ) -> dict:
        progress(5, {"stage": "collecting"})
        collect_result = sa.collect(
            source=request.source,
            platform=request.platform,
            max_items=request.max_items,
            include_comments=request.include_comments,
            include_media=request.include_media,
            deep=request.deep,
            media_max_assets=request.media_max_assets,
        )
        counts = {
            "items": len(collect_result.items),
            "segments": len(collect_result.segments),
            "assets": len(collect_result.assets),
            "comments": len(collect_result.comments),
        }
        progress(
            45,
            {
                "stage": "distilling",
                "profile_id": collect_result.profile.id,
                "counts": counts,
                "diagnostics": collect_result.diagnostics,
            },
        )
        skill = sa.distill(collect_result.profile.id, item_limit=request.item_limit)
        progress(
            80,
            {
                "stage": "exporting",
                "profile_id": collect_result.profile.id,
                "skill_id": skill.id,
                "counts": counts,
                "diagnostics": collect_result.diagnostics,
            },
        )
        output_path = sa.export(skill.id)
        return {
            "stage": "done",
            "profile": collect_result.profile.to_dict(),
            "skill": skill.to_dict(),
            "output_path": str(output_path),
            "counts": counts,
            "diagnostics": collect_result.diagnostics,
        }

    return _submit_job("profile_full_run", payload, runner)


@api.post("/collect")
def collect(request: CollectRequest) -> dict:
    sa = SkillAnythingApp()
    try:
        result = sa.collect(
            source=request.source,
            platform=request.platform,
            max_items=request.max_items,
            include_comments=request.include_comments,
            include_media=request.include_media,
            deep=request.deep,
            media_max_assets=request.media_max_assets,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "profile": result.profile.to_dict(),
        "counts": {
            "items": len(result.items),
            "segments": len(result.segments),
            "assets": len(result.assets),
            "comments": len(result.comments),
        },
        "diagnostics": result.diagnostics,
    }


@api.post("/profiles/{profile_id}/ask")
def ask(profile_id: str, request: AskRequest) -> dict:
    sa = SkillAnythingApp()
    try:
        return sa.ask(profile_id, request.question, limit=request.limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.post("/profiles/{profile_id}/distill")
def distill(profile_id: str, request: DistillRequest) -> dict:
    sa = SkillAnythingApp()
    try:
        skill = sa.distill(profile_id, item_limit=request.item_limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return skill.to_dict()


@api.post("/profiles/{profile_id}/skills/extract")
def extract_focused_skill(profile_id: str, request: FocusSkillRequest) -> dict:
    sa = SkillAnythingApp()
    try:
        skill = sa.extract_focused_skill(
            profile_id=profile_id,
            focus=request.focus,
            item_limit=request.item_limit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return skill.to_dict()


@api.post("/profiles/{profile_id}/archive-media")
def archive_media(profile_id: str, request: ArchiveMediaRequest) -> dict:
    sa = SkillAnythingApp()
    try:
        result = sa.archive_media(
            profile_id,
            kinds=set(request.kinds) if request.kinds else None,
            limit=request.limit,
            force=request.force,
            workers=request.workers,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.to_dict()


@api.get("/skills")
def skills() -> list[dict]:
    sa = SkillAnythingApp()
    sa.init()
    return sa.repo.list_skills()


@api.post("/skills/{skill_id}/export")
def export(skill_id: str, request: ExportRequest) -> dict:
    sa = SkillAnythingApp()
    try:
        path = sa.export(skill_id, Path(request.output_root) if request.output_root else None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"path": str(path)}


def _submit_job(
    job_type: str,
    request: dict[str, Any],
    runner: Callable[[SkillAnythingApp, Callable[[int, dict[str, Any] | None], None]], dict],
) -> dict:
    sa = SkillAnythingApp()
    sa.init()
    job_id = uuid.uuid4().hex
    sa.repo.create_job(job_id, job_type, request)
    _JOB_EXECUTOR.submit(_run_job, job_id, runner)
    row = sa.repo.get_job(job_id)
    return row or {"id": job_id, "status": "queued"}


def _run_job(
    job_id: str,
    runner: Callable[[SkillAnythingApp, Callable[[int, dict[str, Any] | None], None]], dict],
) -> None:
    sa = SkillAnythingApp()
    sa.init()
    sa.repo.update_job(job_id, status="running", progress=1, started=True)

    def progress(value: int, partial: dict[str, Any] | None = None) -> None:
        sa.repo.update_job(
            job_id,
            status="running",
            progress=max(0, min(99, value)),
            result=partial,
        )

    try:
        result = runner(sa, progress)
    except Exception as exc:
        sa.repo.update_job(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished=True,
        )
        return
    sa.repo.update_job(
        job_id,
        status="succeeded",
        progress=100,
        result=result,
        error="",
        finished=True,
    )


def _settings_response(sa: SkillAnythingApp) -> dict:
    return {
        "home": str(sa.settings.home),
        "db": str(sa.settings.db_path),
        "llm": {
            "base_url": sa.settings.llm_base_url or "",
            "model": sa.settings.llm_model or "",
            "api_key_set": bool(sa.settings.llm_api_key),
        },
        "vision": {
            "base_url": sa.settings.vision_base_url or "",
            "model": sa.settings.vision_model or "",
            "api_key_set": bool(sa.settings.vision_api_key),
        },
        "asr": {
            "base_url": sa.settings.asr_base_url or "",
            "model": sa.settings.asr_model or "",
            "language": sa.settings.asr_language or "",
            "api_key_set": bool(sa.settings.asr_api_key),
        },
        "xueqiu": {"cookie_set": bool(sa.settings.xueqiu_cookie)},
        "browser": {"cdp_url": sa.settings.cdp_url},
        "media_max_assets": sa.settings.media_max_assets,
    }


_INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SkillAnything Local</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #607083;
      --line: #dce3ea;
      --accent: #2563eb;
      --accent-dark: #1d4ed8;
      --danger: #b42318;
      --ok: #067647;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      padding: 22px 28px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 {
      margin: 0 0 6px;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0;
    }
    header p {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      grid-template-columns: minmax(320px, 440px) 1fr;
      gap: 20px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 16px;
      font-weight: 650;
    }
    label {
      display: block;
      margin: 12px 0 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
      color: var(--text);
    }
    textarea {
      min-height: 104px;
      resize: vertical;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 120px;
      gap: 10px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }
    button {
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      padding: 10px 13px;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
      min-height: 40px;
    }
    button.secondary {
      background: #e8eef8;
      color: #183153;
    }
    button:hover { background: var(--accent-dark); }
    button.secondary:hover { background: #d8e2f2; }
    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    .status {
      min-height: 36px;
      margin-top: 14px;
      padding: 10px 12px;
      border-radius: 6px;
      background: #f1f5f9;
      color: var(--muted);
      font-size: 13px;
      white-space: pre-wrap;
    }
    .status.error {
      background: #fef3f2;
      color: var(--danger);
    }
    .status.ok {
      background: #ecfdf3;
      color: var(--ok);
    }
    pre {
      min-height: 460px;
      margin: 0;
      overflow: auto;
      border-radius: 6px;
      background: #101828;
      color: #d6e2f0;
      padding: 14px;
      font-size: 13px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .meta {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric {
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
    }
    .metric strong {
      display: block;
      font-size: 18px;
    }
    .metric span {
      color: var(--muted);
      font-size: 12px;
    }
    .full { grid-column: 1 / -1; }
    .stack { display: grid; gap: 14px; }
    .hint { color: var(--muted); font-size: 12px; line-height: 1.5; }
    .source-list {
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }
    .source-item {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #f8fafc;
      font-size: 13px;
    }
    .source-item a { color: var(--accent); text-decoration: none; }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; padding: 14px; }
      .row { grid-template-columns: 1fr; }
      .meta { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>SkillAnything Local</h1>
    <p>输入主页链接，后台采集、蒸馏、导出；随后对知识库问答或提取主题 Skill。</p>
  </header>
  <main>
    <section>
      <h2>一键蒸馏</h2>
      <label for="source">主页链接</label>
      <input id="source" placeholder="https://xueqiu.com/u/2445021949" />
      <div class="row">
        <div>
          <label for="platform">平台</label>
          <select id="platform">
            <option value="">自动识别</option>
            <option value="xueqiu">雪球</option>
            <option value="xiaohongshu">小红书</option>
            <option value="x">X</option>
            <option value="taoguba">淘股吧</option>
            <option value="jiuyangongshe">韭研公社</option>
            <option value="bilibili">B站</option>
          </select>
        </div>
        <div>
          <label for="maxItems">数量</label>
          <input id="maxItems" type="number" min="1" max="1000" value="50" />
        </div>
      </div>
      <div class="row">
        <div>
          <label for="mediaMode">媒体分析</label>
          <select id="mediaMode">
            <option value="false">仅文本</option>
            <option value="true">启用媒体</option>
          </select>
        </div>
        <div>
          <label for="mediaMaxAssets">媒体上限</label>
          <input id="mediaMaxAssets" type="number" min="0" max="5000" value="20" />
        </div>
      </div>
      <div class="actions">
        <button id="runBtn" onclick="startFullRun()">开始蒸馏</button>
        <button class="secondary" onclick="loadProfiles()">刷新 Profile</button>
      </div>
      <div id="status" class="status">等待任务。</div>
      <p class="hint" id="configStatus">配置状态加载中。</p>
    </section>

    <section>
      <h2>知识库</h2>
      <label for="profileSelect">Profile</label>
      <select id="profileSelect" onchange="selectProfile()"></select>
      <div class="meta">
        <div class="metric"><strong id="itemCount">0</strong><span>内容</span></div>
        <div class="metric"><strong id="assetCount">0</strong><span>媒体</span></div>
        <div class="metric"><strong id="segmentCount">0</strong><span>片段</span></div>
      </div>
      <div class="actions">
        <button class="secondary" onclick="loadItems()">查看帖子</button>
        <button class="secondary" onclick="loadSkills()">查看 Skill</button>
      </div>
    </section>

    <section class="full">
      <h2>模型/API 设置</h2>
      <div class="row">
        <div>
          <label for="llmBase">文本模型 Base URL</label>
          <input id="llmBase" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
        </div>
        <div>
          <label for="llmModel">文本模型</label>
          <input id="llmModel" placeholder="qwen-plus / qwen3-vl-plus" />
        </div>
      </div>
      <label for="llmKey">文本模型 API Key</label>
      <input id="llmKey" type="password" placeholder="留空表示不修改已保存的 key" />
      <div class="row">
        <div>
          <label for="visionBase">视觉模型 Base URL</label>
          <input id="visionBase" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
        </div>
        <div>
          <label for="visionModel">视觉模型</label>
          <input id="visionModel" placeholder="qwen3-vl-plus" />
        </div>
      </div>
      <label for="visionKey">视觉模型 API Key</label>
      <input id="visionKey" type="password" placeholder="留空表示不修改已保存的 key" />
      <div class="row">
        <div>
          <label for="asrBase">ASR Base URL</label>
          <input id="asrBase" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
        </div>
        <div>
          <label for="asrModel">ASR 模型</label>
          <input id="asrModel" placeholder="qwen3-asr-flash" />
        </div>
      </div>
      <div class="row">
        <div>
          <label for="asrKey">ASR API Key</label>
          <input id="asrKey" type="password" placeholder="留空表示不修改已保存的 key" />
        </div>
        <div>
          <label for="asrLanguage">ASR 语言</label>
          <input id="asrLanguage" placeholder="zh" />
        </div>
      </div>
      <div class="row">
        <div>
          <label for="xueqiuCookie">雪球 Cookie</label>
          <input id="xueqiuCookie" type="password" placeholder="留空表示不修改已保存的 Cookie" />
        </div>
        <div>
          <label for="cdpUrl">浏览器 CDP URL</label>
          <input id="cdpUrl" placeholder="http://127.0.0.1:9222" />
        </div>
      </div>
      <div class="actions">
        <button class="secondary" id="saveSettingsBtn" onclick="saveSettings()">保存设置</button>
        <button class="secondary" id="reloadSettingsBtn" onclick="loadSettings()">刷新设置</button>
      </div>
      <div id="settingsStatus" class="status">设置不会在页面回显 API Key。</div>
    </section>

    <section>
      <h2>问答</h2>
      <label for="question">问题</label>
      <textarea id="question" placeholder="例如：某个帖子说了什么？他如何分析美股风险？"></textarea>
      <div class="actions">
        <button id="askBtn" onclick="askProfile()">提问</button>
      </div>
      <div id="answer" class="status">选择 Profile 后开始提问。</div>
      <div id="sources" class="source-list"></div>
    </section>

    <section>
      <h2>提取特定 Skill</h2>
      <label for="focus">主题</label>
      <input id="focus" placeholder="例如：美股风险分析" />
      <div class="actions">
        <button id="focusBtn" onclick="extractSkill()">提取 Skill</button>
        <button class="secondary" id="exportBtn" onclick="exportSkill()" disabled>
          导出当前 Skill
        </button>
      </div>
      <div id="skillStatus" class="status">等待主题。</div>
    </section>

    <section class="full">
      <h2>结果</h2>
      <pre id="output">{}</pre>
    </section>
  </main>
  <script>
    let profileId = null;
    let skillId = null;
    let pollTimer = null;

    function showStatus(id, text, kind = "") {
      const el = document.getElementById(id);
      el.className = "status " + kind;
      el.textContent = text;
    }

    function showOutput(data) {
      document.getElementById("output").textContent = JSON.stringify(data, null, 2);
    }

    async function getJson(path) {
      const res = await fetch(path);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      return data;
    }

    async function postJson(path, body) {
      const res = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      return data;
    }

    function setBusy(isBusy) {
      document.getElementById("runBtn").disabled = isBusy;
      document.getElementById("askBtn").disabled = isBusy || !profileId;
      document.getElementById("focusBtn").disabled = isBusy || !profileId;
      document.getElementById("exportBtn").disabled = isBusy || !skillId;
    }

    async function loadConfig() {
      try {
        const data = await getJson("/config/status");
        const items = [
          "LLM " + (data.llm_configured ? "已配置" : "未配置"),
          "Vision " + (data.vision_configured ? "已配置" : "未配置"),
          "ASR " + (data.asr_configured ? "已配置" : "未配置"),
          "雪球 Cookie " + (data.xueqiu_cookie_configured ? "已配置" : "未配置"),
        ];
        document.getElementById("configStatus").textContent = items.join(" / ");
      } catch (err) {
        document.getElementById("configStatus").textContent = err.message;
      }
    }

    async function loadSettings() {
      try {
        const data = await getJson("/settings");
        document.getElementById("llmBase").value = data.llm.base_url || "";
        document.getElementById("llmModel").value = data.llm.model || "";
        document.getElementById("visionBase").value = data.vision.base_url || "";
        document.getElementById("visionModel").value = data.vision.model || "";
        document.getElementById("asrBase").value = data.asr.base_url || "";
        document.getElementById("asrModel").value = data.asr.model || "";
        document.getElementById("asrLanguage").value = data.asr.language || "";
        document.getElementById("cdpUrl").value = data.browser.cdp_url || "";
        document.getElementById("llmKey").placeholder =
          data.llm.api_key_set ? "已设置，留空不修改" : "未设置";
        document.getElementById("visionKey").placeholder =
          data.vision.api_key_set ? "已设置，留空不修改" : "未设置";
        document.getElementById("asrKey").placeholder =
          data.asr.api_key_set ? "已设置，留空不修改" : "未设置";
        document.getElementById("xueqiuCookie").placeholder =
          data.xueqiu.cookie_set ? "已设置，留空不修改" : "未设置";
        showStatus("settingsStatus", "设置已加载。", "ok");
      } catch (err) {
        showStatus("settingsStatus", err.message, "error");
      }
    }

    async function saveSettings() {
      const body = {
        llm_base_url: document.getElementById("llmBase").value,
        llm_model: document.getElementById("llmModel").value,
        vision_base_url: document.getElementById("visionBase").value,
        vision_model: document.getElementById("visionModel").value,
        asr_base_url: document.getElementById("asrBase").value,
        asr_model: document.getElementById("asrModel").value,
        asr_language: document.getElementById("asrLanguage").value,
        cdp_url: document.getElementById("cdpUrl").value,
        media_max_assets: Number(document.getElementById("mediaMaxAssets").value || 80),
      };
      const llmKey = document.getElementById("llmKey").value.trim();
      const visionKey = document.getElementById("visionKey").value.trim();
      const asrKey = document.getElementById("asrKey").value.trim();
      const xueqiuCookie = document.getElementById("xueqiuCookie").value.trim();
      if (llmKey) body.llm_api_key = llmKey;
      if (visionKey) body.vision_api_key = visionKey;
      if (asrKey) body.asr_api_key = asrKey;
      if (xueqiuCookie) body.xueqiu_cookie = xueqiuCookie;
      try {
        const data = await postJson("/settings", body);
        document.getElementById("llmKey").value = "";
        document.getElementById("visionKey").value = "";
        document.getElementById("asrKey").value = "";
        document.getElementById("xueqiuCookie").value = "";
        showStatus("settingsStatus", "设置已保存。", "ok");
        showOutput({settings: data});
        await loadConfig();
        await loadSettings();
      } catch (err) {
        showStatus("settingsStatus", err.message, "error");
      }
    }

    async function loadProfiles() {
      const profiles = await getJson("/profiles");
      const select = document.getElementById("profileSelect");
      select.innerHTML = "";
      for (const profile of profiles) {
        const option = document.createElement("option");
        option.value = profile.id;
        const label = profile.display_name || profile.handle || profile.id;
        option.textContent = `${label} (${profile.platform})`;
        select.appendChild(option);
      }
      if (profiles.length) {
        profileId = select.value || profiles[0].id;
        await loadItems();
      }
      setBusy(false);
    }

    function selectProfile() {
      profileId = document.getElementById("profileSelect").value || null;
      skillId = null;
      setBusy(false);
    }

    async function loadItems() {
      if (!profileId) return;
      const items = await getJson(`/profiles/${profileId}/items?limit=20`);
      document.getElementById("itemCount").textContent = items.length;
      document.getElementById("assetCount").textContent = "-";
      document.getElementById("segmentCount").textContent = "-";
      showOutput({profile_id: profileId, items});
    }

    async function loadSkills() {
      const skills = await getJson("/skills");
      const filtered = profileId ? skills.filter(s => s.profile_id === profileId) : skills;
      if (filtered.length) skillId = filtered[0].id;
      showOutput({skills: filtered});
      setBusy(false);
    }

    async function startFullRun() {
      setBusy(true);
      showStatus("status", "任务已提交，等待启动...");
      try {
        const job = await postJson("/jobs/profile-full-run", {
          source: document.getElementById("source").value,
          platform: document.getElementById("platform").value || null,
          max_items: Number(document.getElementById("maxItems").value || 50),
          include_comments: false,
          include_media: document.getElementById("mediaMode").value === "true",
          deep: true,
          media_max_assets: Number(document.getElementById("mediaMaxAssets").value || 20),
          item_limit: 200,
        });
        showOutput(job);
        pollJob(job.id);
      } catch (err) {
        showStatus("status", err.message, "error");
        setBusy(false);
      }
    }

    async function pollJob(jobId) {
      if (pollTimer) clearTimeout(pollTimer);
      try {
        const job = await getJson(`/jobs/${jobId}`);
        showOutput(job);
        const result = job.result || {};
        showStatus("status", `${job.status}: ${job.progress}/${job.total} ${result.stage || ""}`);
        if (result.profile_id || result.profile?.id) {
          profileId = result.profile_id || result.profile.id;
        }
        if (result.skill_id || result.skill?.id) {
          skillId = result.skill_id || result.skill.id;
        }
        if (result.counts) {
          document.getElementById("itemCount").textContent = result.counts.items ?? 0;
          document.getElementById("assetCount").textContent = result.counts.assets ?? 0;
          document.getElementById("segmentCount").textContent = result.counts.segments ?? 0;
        }
        if (job.status === "succeeded") {
          showStatus("status", "蒸馏完成：" + (result.output_path || ""), "ok");
          await loadProfiles();
          setBusy(false);
          return;
        }
        if (job.status === "failed") {
          showStatus("status", job.error || "任务失败", "error");
          setBusy(false);
          return;
        }
        pollTimer = setTimeout(() => pollJob(jobId), 1500);
      } catch (err) {
        showStatus("status", err.message, "error");
        setBusy(false);
      }
    }

    async function askProfile() {
      if (!profileId) return;
      setBusy(true);
      showStatus("answer", "正在检索知识库...");
      document.getElementById("sources").innerHTML = "";
      try {
        const data = await postJson(`/profiles/${profileId}/ask`, {
          question: document.getElementById("question").value,
          limit: 8,
        });
        showStatus("answer", data.answer, "ok");
        renderSources(data.sources || []);
        showOutput(data);
      } catch (err) {
        showStatus("answer", err.message, "error");
      } finally {
        setBusy(false);
      }
    }

    function renderSources(sources) {
      const root = document.getElementById("sources");
      root.innerHTML = "";
      for (const source of sources) {
        const item = document.createElement("div");
        item.className = "source-item";
        const title = source.title || source.kind;
        const link = source.url
          ? `<a href="${source.url}" target="_blank">${title}</a>`
          : title;
        item.innerHTML = `<strong>${link}</strong><br>${source.snippet || ""}`;
        root.appendChild(item);
      }
    }

    async function extractSkill() {
      if (!profileId) return;
      setBusy(true);
      showStatus("skillStatus", "正在提取主题 Skill...");
      try {
        const data = await postJson(`/profiles/${profileId}/skills/extract`, {
          focus: document.getElementById("focus").value,
          item_limit: 80,
        });
        skillId = data.id;
        showStatus("skillStatus", "提取完成，skill id: " + skillId, "ok");
        showOutput(data);
      } catch (err) {
        showStatus("skillStatus", err.message, "error");
      } finally {
        setBusy(false);
      }
    }

    async function exportSkill() {
      if (!skillId) return;
      setBusy(true);
      showStatus("skillStatus", "正在导出...");
      try {
        const data = await postJson("/skills/" + skillId + "/export", {});
        showStatus("skillStatus", "导出完成：" + data.path, "ok");
        showOutput(data);
      } catch (err) {
        showStatus("skillStatus", err.message, "error");
      } finally {
        setBusy(false);
      }
    }

    loadConfig();
    loadSettings();
    loadProfiles().catch(err => showStatus("status", err.message, "error"));
  </script>
</body>
</html>
"""
