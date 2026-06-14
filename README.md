# SkillAnything Local

Local-first pipeline for turning public community homepages into agent-ready Skill packages.

Current capabilities:

- Collect Xiaohongshu profiles with text, images, video, subtitles, and optional ASR/Vision.
- Collect Xueqiu users as text-only profiles.
- Normalize profiles, posts, media, text segments, comments, and skills into SQLite.
- Distill a profile into `SKILL.md`, `posts/`, `分析/`, references, evals, and `skill.yaml`.
- Ask questions against the local knowledge base.
- Extract focused skills such as `美股风险分析` from an existing profile.
- Use from CLI or the built-in FastAPI web console.

This project does not bypass CAPTCHA, paid walls, login restrictions, or platform anti-abuse systems.
Use it only with content you are authorized to access.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,browser,media,vector]"
```

Copy `.env.example` to `.env` and configure your own keys.

```powershell
Copy-Item .env.example .env
```

## Quick Start

Start the web console:

```powershell
sa ui --host 127.0.0.1 --port 9000
```

Open `http://127.0.0.1:9000/`.

Use the UI to:

1. Paste a homepage link, for example `https://xueqiu.com/u/2445021949`.
2. Open `模型/API 设置` and configure your Qwen/DashScope-compatible text model.
3. Choose platform or leave auto-detect.
4. Click `开始蒸馏`.
5. Ask questions against the generated knowledge base.
6. Extract a focused Skill and export it.

CLI equivalent:

```powershell
sa init
sa collect "https://xueqiu.com/u/2445021949" --platform xueqiu --max-items 20 --no-media
sa profiles
sa distill <profile-id>
sa ask <profile-id> "他如何分析美股风险？"
sa extract-skill <profile-id> "美股风险分析"
sa export <skill-id>
```

## Web Console

The built-in console is designed to work without a separate frontend build step.

Main sections:

- `当前使用模型`: shows the active text, image, and ASR models and their provider base URLs.
- `一键蒸馏`: paste a homepage URL, choose platform, set item count, and start a background job.
- `知识库`: select a collected profile and inspect recently collected posts.
- `模型/API 设置`: configure providers from the browser without editing `.env`.
- `问答`: ask questions such as "某个帖子说了什么？" or "他如何分析美股风险？".
- `提取特定 Skill`: generate a focused Skill from the profile knowledge base.

Provider settings saved in the UI are stored in local SQLite under `SKILLANYTHING_HOME`. API keys
and cookies are never echoed back to the page; the UI only shows whether a secret is configured.
The header contains a direct `设置模型/API` entry so new users can configure providers before
running their first distillation.

Recommended Qwen/DashScope-compatible values:

```text
Text Base URL:   https://dashscope.aliyuncs.com/compatible-mode/v1
Text Model:      qwen-plus or qwen3-vl-plus
Vision Model:    qwen3-vl-plus
ASR Model:       qwen3-asr-flash
ASR Language:    zh
```

## Platform Notes

### Xueqiu

Xueqiu collection is text-only. The connector reads:

- post text and long-form detail pages
- title or generated text title
- publish time
- source URL
- repost/comment/like metrics
- reposted status text when present

Without `SKILLANYTHING_XUEQIU_COOKIE`, Xueqiu usually exposes only the first public timeline page.
To fetch more pages, copy your own logged-in browser Cookie into `.env`:

```dotenv
SKILLANYTHING_XUEQIU_COOKIE=xq_a_token=...; xq_id_token=...; u=...
```

Test URL:

```powershell
sa collect "https://xueqiu.com/u/2445021949" --platform xueqiu --max-items 20 --no-media
```

### Xiaohongshu

For deep Xiaohongshu collection, expose a logged-in Chrome session:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:TEMP\skillanything-chrome"
```

Then log in to Xiaohongshu in that browser and run:

```powershell
sa collect "https://www.xiaohongshu.com/user/profile/<id>" --platform xiaohongshu --max-items 100
```

Vision and ASR are optional. If omitted, text distillation still works.

## API

The local API defaults to no authentication and should be bound to `127.0.0.1`.
Do not expose it directly to the public internet.

Useful endpoints:

- `GET /config/status`: configured provider status without leaking keys.
- `GET /settings`: saved provider settings with only boolean secret status.
- `POST /settings`: save provider settings locally.
- `POST /jobs/profile-full-run`: collect, distill, and export in a background job.
- `GET /jobs/{job_id}`: poll job status.
- `GET /profiles`: list collected profiles.
- `GET /profiles/{profile_id}/items`: list posts.
- `POST /profiles/{profile_id}/ask`: ask the knowledge base.
- `POST /profiles/{profile_id}/skills/extract`: extract a focused Skill.
- `POST /skills/{skill_id}/export`: export a Skill package.

Example:

```powershell
$job = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:9000/jobs/profile-full-run `
  -ContentType application/json `
  -Body '{"source":"https://xueqiu.com/u/2445021949","platform":"xueqiu","max_items":20,"include_media":false}'

Invoke-RestMethod http://127.0.0.1:9000/jobs/$($job.id)
```

## Configuration

Core variables:

- `SKILLANYTHING_HOME`: SQLite database, archive, and output root. Defaults to `./data`.
- `SKILLANYTHING_LLM_BASE_URL`, `SKILLANYTHING_LLM_API_KEY`, `SKILLANYTHING_LLM_MODEL`: OpenAI-compatible LLM for distillation and Q&A.
- `SKILLANYTHING_VISION_BASE_URL`, `SKILLANYTHING_VISION_API_KEY`, `SKILLANYTHING_VISION_MODEL`: OpenAI-compatible vision model.
- `SKILLANYTHING_ASR_BASE_URL`, `SKILLANYTHING_ASR_API_KEY`, `SKILLANYTHING_ASR_MODEL`: ASR provider.
- `SKILLANYTHING_XUEQIU_COOKIE`: optional logged-in Xueqiu Cookie.
- `SKILLANYTHING_CDP_URL`: Chrome DevTools endpoint for browser-assisted collection.

If no LLM key is configured, distillation and Q&A use deterministic local fallbacks so the pipeline
remains testable.

The same provider values can be configured in the web console. They are saved locally in SQLite and
are not echoed back to the page after saving.

## Testing

```powershell
pytest -q
python -m compileall skillanything
python -m ruff check .
```

End-to-end smoke checks:

```powershell
# Xueqiu text-only collection
sa collect "https://xueqiu.com/u/2445021949" --platform xueqiu --max-items 20 --no-media

# Start the web console and run the same URL from the browser
sa ui --host 127.0.0.1 --port 9000
```

Expected Xueqiu behavior without Cookie:

- first public timeline page can be collected
- additional pages may return `login_required_for_more_pages`
- no media assets are created for Xueqiu

For a local Williams regression test, point `SKILLANYTHING_HOME` at an existing local database:

```powershell
$env:SKILLANYTHING_HOME="D:\Data\HC_PROJECT\v2\SkillAnything\data\full-run-williams-final-20260527"
sa ask d4f261b35690b713d0d721147a5ba599 "请告诉我应该如何分析美股的风险"
sa extract-skill d4f261b35690b713d0d721147a5ba599 "美股风险分析"
```

Do not commit local `data/`, `.env`, generated archives, or exported private profiles.

## Local Data

By default, runtime state is written under `./data`:

- `skillanything.sqlite3`: profiles, posts, segments, skills, jobs, settings, and search index
- `archive/`: downloaded images, videos, subtitles, and extracted audio
- `output/`: exported Skill packages

These files can contain copyrighted content, private cookies, API-derived outputs, and local
credentials. They are intentionally ignored by Git and should not be included in open-source commits.

## Architecture

- `connectors`: platform adapters and routing.
- `storage`: SQLite repository, jobs, and knowledge index.
- `extract`: text/media normalization helpers.
- `distill`: profile-to-skill synthesis.
- `package`: Skill package writer and linter.
- `qa`: knowledge-base Q&A.
- `web`: local FastAPI API and built-in console.

## SkillAnything v1 Workbench

This repository now includes an additive v1 architecture that keeps the old CLI/API compatible while
adding a clearer three-layer pipeline:

- Data source layer: existing connectors are adapted upward into `SourceDocument` and `Corpus` IR.
  Custom sources can implement the `SourceAdapter` protocol in `skillanything/sources/base.py`.
- Distillation layer: `CapabilityDistillationPipeline` turns a corpus into typed `Capability`
  records. It supports autonomous discovery and user-defined capability extraction through a focus,
  capability type, and optional schema.
- Skill packaging layer: `SkillPackExporter` exports the same `SkillPack` IR to `codex-skill`,
  `openai-skill`, `claude-skill`, `claude-project-bundle`, or `json-ir`.

Core IR and services:

- `skillanything/ir.py`: `SourceDocument`, `Corpus`, `Capability`, `SkillPack`.
- `skillanything/sources/`: normalized data-source adapter contract.
- `skillanything/distill/pipeline.py`: capability distillation orchestration.
- `skillanything/package/exporters/`: multi-platform exporters.
- `skillanything/storage/repository.py`: additive tables for collection runs, corpora,
  capabilities, evidence links, skill packs, export artifacts, and richer jobs.

New CLI examples:

```powershell
sa build-corpus <profile_id> --goal "提取产业链研究方法"
sa extract-capability <profile_id> "中国 A 股产业链相关性挖掘" --type chain_relevance_mining
sa capabilities --profile-id <profile_id>
sa create-pack <capability_id> --target codex-skill --target claude-skill
sa export-pack <pack_id> --target claude-project-bundle
```

New v1 API examples:

```powershell
Invoke-RestMethod http://127.0.0.1:8091/api/v1/sources/connectors

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8091/api/v1/capabilities:extract `
  -ContentType application/json `
  -Body '{"profile_id":"<profile_id>","focus":"中国 A 股产业链相关性挖掘","capability_type":"chain_relevance_mining"}'

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8091/api/v1/packs/<pack_id>/exports `
  -ContentType application/json `
  -Body '{"target":"json-ir"}'
```

Frontend workbench:

```powershell
# Backend
sa ui --host 127.0.0.1 --port 8091

# Frontend
cd frontend
npm install
$env:VITE_SKILLANYTHING_API_PROXY="http://127.0.0.1:8091"
npm run dev
```

Open `http://127.0.0.1:5176`. The workbench exposes: new data source, source library, distillation
workspace, evidence review, Skill library, tasks/logs, and model/API settings.
