# SkillAnything Local

SkillAnything 是一个本地优先的 Skill 蒸馏工厂：从公开内容、主页、帖子、媒体转写、评论和本地文件中提取可复用能力，并打包成不同 AI 平台可使用的 Skill。

它的目标不是复刻某个创作者本人，而是从证据中抽取可迁移的方法、流程、判断规则、表达习惯、边界条件和评测用例。

## 设计目标

- 本地优先：SQLite、本地归档、本地导出，默认不依赖云端服务。
- 证据约束：所有强规则都应能追溯到来源内容，低置信度结论要显式标记。
- 通用蒸馏：不把所有内容强行套进宏观分析、投研分析或营销模板。
- 可扩展数据源：不同来源向上输出统一结构，方便新增 connector。
- Planner-driven：先由 Planner Agent 阅读内容并设计蒸馏任务，再执行 Skill 生成。
- 多平台封装：同一份 IR 可以导出为 Codex Skill、OpenAI Skill、Claude Skill、Claude Project Bundle 或 JSON IR。

## 总体架构

```text
Data Source
  URL / local file / profile / RSS / media / comments
        |
        v
Source Layer
  Connector -> SourceDocument -> Corpus
        |
        v
Distillation Layer
  DistillationPlanner -> DistillationPlan
  Distiller -> DistilledSkill
  CapabilityDistillationPipeline -> Capability + EvidenceLink
        |
        v
Packaging Layer
  SkillPack -> target exporters
        |
        v
Codex Skill / OpenAI Skill / Claude Skill / Claude Project Bundle / JSON IR
```

核心模块：

- `skillanything/connectors/`: 平台和文件采集器。
- `skillanything/sources/`: 数据源层适配协议，把采集结果统一成 SourceDocument。
- `skillanything/ir.py`: SourceDocument、Corpus、Capability、SkillPack 等中间表示。
- `skillanything/distill/planner.py`: Planner Agent，负责设计蒸馏任务。
- `skillanything/distill/distiller.py`: 通用蒸馏执行器，支持 LLM 和本地 fallback。
- `skillanything/distill/pipeline.py`: 串联 Corpus、Plan、Skill、Capability、Pack。
- `skillanything/package/exporters/`: 多平台导出器。
- `skillanything/storage/repository.py`: SQLite 持久化、任务、索引、导出记录。
- `skillanything/web.py`: FastAPI API 和旧版内置控制台。
- `frontend/`: Vue 3 工作台。

## 三层机制

### 1. 数据源层

数据源层负责把不同来源统一为上层可消费的数据结构。

输入可以是：

- 本地文件
- Web 页面
- 小红书主页
- 雪球用户
- X / Twitter 内容
- RSSHub
- 未来新增的自定义数据源

统一向上输出：

- `SourceDocument`: 单篇内容、标题、正文、来源 URL、指标、媒体、片段、评论。
- `Corpus`: 面向一次蒸馏任务的语料集合，包含 profile、documents、目标、能力请求和统计信息。

扩展新数据源时，可以实现 `skillanything/sources/base.py` 中的 `SourceAdapter`，或复用现有 connector 并把结果转成 `SourceDocument`。

### 2. 蒸馏层

蒸馏层是核心。

过去版本的本地 fallback 偏向宏观分析，会默认使用“指标、传导链、风险情景”等模板。现在已经改成 Planner-driven：

```text
Corpus + goal + capability_type + schema
        |
        v
DistillationPlanner
        |
        v
DistillationPlan
        |
        v
Distiller
        |
        v
DistilledSkill
```

`DistillationPlan` 包含：

- `domain`: 识别出的任务领域。
- `capability_type`: 要抽取的能力类型。
- `extraction_targets`: 需要抽取哪些能力要素。
- `evidence_questions`: 应该向语料追问哪些证据问题。
- `workflow_axes`: 生成 Skill 时的工作流轴线。
- `style_axes`: 输出风格约束。
- `guardrails`: 防冒充、防过拟合、防无证据推断的规则。
- `eval_scenarios`: 评测场景。
- `output_schema`: 用户自定义或默认输出结构。
- `tasks`: 具体蒸馏任务拆解。

当前内置的通用规划类型：

- `trading_strategy`: 股票交易实盘策略，抽取 setup、entry、exit、position sizing、risk、review。
- `marketing_growth`: 小红书/内容营销/广告增长，抽取 audience、hook、creative、channel、conversion、metrics。
- `industry_research`: 产业链/公司相关性研究，抽取 chain、entities、mechanism、evidence、confidence、watchlist。
- `generic`: 未知领域的通用能力蒸馏，抽取 inputs、rules、workflow、outputs、evidence、limits。

有 LLM 配置时，Distiller 会把 `DistillationPlan` 和证据语料一起发给模型。

没有 LLM 配置时，本地 fallback 也会按 plan 生成可运行 Skill 骨架，不再写死宏观分析模板。

### 3. Skill 封装层

蒸馏结果会被转换为：

- `Capability`: 可审阅、可复用的能力记录。
- `EvidenceLink`: 能力与来源证据之间的链接。
- `SkillPack`: 面向导出的完整包。

支持导出目标：

- `codex-skill`
- `openai-skill`
- `claude-skill`
- `claude-project-bundle`
- `json-ir`

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,browser,media,vector]"
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

可选模型配置：

```dotenv
SKILLANYTHING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
SKILLANYTHING_LLM_API_KEY=your-key
SKILLANYTHING_LLM_MODEL=qwen-plus

SKILLANYTHING_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
SKILLANYTHING_VISION_API_KEY=your-key
SKILLANYTHING_VISION_MODEL=qwen3-vl-plus

SKILLANYTHING_ASR_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
SKILLANYTHING_ASR_API_KEY=your-key
SKILLANYTHING_ASR_MODEL=qwen3-asr-flash
```

没有模型 key 时，采集、索引、问答和蒸馏仍可使用本地 fallback 跑通。

## CLI 使用

初始化：

```powershell
sa init
```

采集本地文件：

```powershell
sa collect "D:\data\creator-notes.md" --platform local --max-items 20
```

采集雪球：

```powershell
sa collect "https://xueqiu.com/u/2445021949" --platform xueqiu --max-items 20 --no-media
```

采集小红书：

```powershell
sa collect "https://www.xiaohongshu.com/user/profile/<id>" --platform xiaohongshu --max-items 100
```

查看 profile：

```powershell
sa profiles
sa items <profile_id>
```

自主蒸馏：

```powershell
sa distill <profile_id> --goal "蒸馏这个创作者可复用的方法论"
```

定向蒸馏股票交易实盘策略：

```powershell
sa extract-capability <profile_id> "蒸馏股票交易实盘选手的策略 Skill" --type trading_strategy
```

定向蒸馏小红书广告营销 Skill：

```powershell
sa extract-capability <profile_id> "提取小红书自媒体广告营销 Skill" --type marketing_growth
```

定向蒸馏产业链相关性挖掘 Skill：

```powershell
sa extract-capability <profile_id> "中国 A 股产业链相关性挖掘" --type chain_relevance_mining
```

查看能力和打包：

```powershell
sa capabilities --profile-id <profile_id>
sa create-pack <capability_id> --target codex-skill --target claude-skill
sa export-pack <pack_id> --target claude-project-bundle
```

导出旧 Skill：

```powershell
sa skills
sa export <skill_id> --target codex-skill
```

本地知识库问答：

```powershell
sa ask <profile_id> "这个创作者如何做交易复盘？"
```

## API 使用

启动后端：

```powershell
sa ui --host 127.0.0.1 --port 8091
```

常用旧 API：

- `GET /health`
- `GET /profiles`
- `GET /profiles/{profile_id}/items`
- `POST /profiles/{profile_id}/distill`
- `POST /profiles/{profile_id}/ask`
- `POST /profiles/{profile_id}/skills/extract`
- `POST /skills/{skill_id}/export`
- `POST /jobs/profile-full-run`

新增 v1 API：

- `GET /api/v1/sources/connectors`
- `POST /api/v1/sources:collect`
- `POST /api/v1/corpora`
- `GET /api/v1/corpora`
- `POST /api/v1/profiles/{profile_id}/capabilities:discover`
- `POST /api/v1/capabilities:extract`
- `GET /api/v1/capabilities`
- `POST /api/v1/capabilities/{capability_id}:review`
- `POST /api/v1/capabilities/{capability_id}/packs`
- `GET /api/v1/packs`
- `POST /api/v1/packs/{pack_id}/exports`
- `GET /api/v1/exports`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}/events`

示例：定向提取 Capability。

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8091/api/v1/capabilities:extract `
  -ContentType application/json `
  -Body '{
    "profile_id": "<profile_id>",
    "focus": "提取小红书自媒体广告营销 Skill",
    "capability_type": "marketing_growth",
    "schema": {
      "outputs": ["audience", "hook", "creative", "channel", "conversion", "metrics", "evidence"]
    }
  }'
```

示例：导出 JSON IR。

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8091/api/v1/packs/<pack_id>/exports `
  -ContentType application/json `
  -Body '{"target":"json-ir"}'
```

## 前端工作台

后端：

```powershell
sa ui --host 127.0.0.1 --port 8091
```

前端：

```powershell
cd frontend
npm install
$env:VITE_SKILLANYTHING_API_PROXY="http://127.0.0.1:8091"
npm run dev
```

打开：

```text
http://127.0.0.1:5176
```

工作台包含：

- 新建数据源
- 来源库
- 蒸馏工作台
- 证据审阅
- Skill 库
- 任务与日志
- 模型/API 设置

## 数据源说明

### 雪球

雪球 connector 当前以文本采集为主，支持：

- 用户主页
- 帖子正文
- 长文详情页
- 发布时间
- 来源 URL
- 转发、评论、点赞等指标

如需更多页面，配置自己的登录 Cookie：

```dotenv
SKILLANYTHING_XUEQIU_COOKIE=xq_a_token=...; xq_id_token=...; u=...
```

### 小红书

深度采集小红书时，可以打开一个带远程调试端口的 Chrome：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:TEMP\skillanything-chrome"
```

然后在该浏览器中登录小红书，再执行采集。

## 扩展 Planner

新增一种能力类型时，优先扩展 `skillanything/distill/planner.py`：

1. 增加 domain spec。
2. 定义 `keywords`，用于本地识别领域。
3. 定义 `targets`，说明要抽取哪些能力要素。
4. 定义 `evidence_questions`，说明要向语料追问哪些证据。
5. 定义 `workflow_axes` 和 `style_axes`。
6. 定义 `guardrails`，防止无证据泛化。
7. 定义 `eval_scenarios`，用于生成测试用例。
8. 定义默认 `schema`。

如果用户传入自定义 schema，Planner 会把用户 schema 与默认 schema 合并。

## 测试

```powershell
python -m compileall skillanything
pytest -q --basetemp .tmp_pytest_run -p no:cacheprovider
cd frontend
npm run build
```

当前重点测试覆盖：

- 本地文件到 Skill 包
- 问答和 focused Skill
- IR / Capability / SkillPack / 多目标导出
- Planner 对 `trading_strategy` 的识别和本地蒸馏
- Planner 对 `marketing_growth` 的识别和本地蒸馏

## 本地数据与安全

默认运行数据写入 `./data`：

- `skillanything.sqlite3`: profile、内容、片段、skills、jobs、settings、IR 和索引。
- `archive/`: 下载的图片、视频、字幕和音频。
- `output/`: 导出的 Skill 包。

这些文件可能包含版权内容、Cookie、API 派生输出和本地凭据，不应提交到公开仓库。

本项目不会绕过验证码、付费墙、登录限制或平台反滥用系统。只采集你有权访问和处理的内容。
