<template>
  <div class="workbench-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">SA</div>
        <div>
          <p>SkillAnything</p>
          <span>本地 Skill 工厂</span>
        </div>
      </div>

      <nav class="nav-list" aria-label="SkillAnything 工作台">
        <button
          v-for="item in navItems"
          :key="item.key"
          type="button"
          class="nav-item"
          :class="{ active: page === item.key }"
          @click="page = item.key"
        >
          <component :is="item.icon" class="icon" />
          <span>{{ item.label }}</span>
          <small v-if="item.badge">{{ item.badge }}</small>
        </button>
      </nav>

      <div class="sidebar-footer">
        <span :class="['status-dot', store.health ? 'ok' : 'warn']" />
        <div>
          <p>{{ store.health ? 'API 已连接' : '等待 API' }}</p>
          <small>{{ apiPath }}</small>
        </div>
      </div>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div>
          <p class="eyebrow">SkillAnything Workbench</p>
          <h1>{{ currentTitle }}</h1>
        </div>
        <div class="topbar-actions">
          <span v-if="store.notice" class="toast ok">{{ store.notice }}</span>
          <span v-if="store.error" class="toast error">{{ store.error }}</span>
          <button type="button" class="ghost-button" :disabled="store.loading" @click="store.refreshAll">
            <RefreshCw class="icon" :class="{ spin: store.loading }" />
            刷新
          </button>
        </div>
      </header>

      <section v-if="page === 'source'" class="content-grid source-grid">
        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Source Layer</p>
              <h2>新建数据源</h2>
            </div>
            <Database class="panel-icon" />
          </div>

          <div class="form-grid">
            <label class="field wide">
              <span>来源地址或本地文件</span>
              <input v-model="sourceForm.source" placeholder="https://... 或 D:\\data\\sample.md" />
            </label>
            <label class="field">
              <span>平台提示</span>
              <select v-model="sourceForm.platform">
                <option value="">自动识别</option>
                <option v-for="connector in store.connectors" :key="connector.platform" :value="connector.platform">
                  {{ connector.platform }}
                </option>
              </select>
            </label>
            <label class="field">
              <span>最大条数</span>
              <input v-model.number="sourceForm.max_items" type="number" min="1" max="1000" />
            </label>
          </div>

          <div class="toggle-row">
            <label><input v-model="sourceForm.include_comments" type="checkbox" /> 评论</label>
            <label><input v-model="sourceForm.include_media" type="checkbox" /> 媒体</label>
            <label><input v-model="sourceForm.deep" type="checkbox" /> 深采集</label>
          </div>

          <div class="action-row">
            <button type="button" class="primary-button" :disabled="store.loading" @click="collectNow">
              <Play class="icon" />
              立即采集
            </button>
            <button type="button" class="secondary-button" :disabled="store.loading" @click="queueCollect">
              <ListPlus class="icon" />
              放入任务队列
            </button>
          </div>
        </div>

        <div class="panel compact">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Connectors</p>
              <h2>已封装数据源</h2>
            </div>
          </div>
          <div class="connector-list">
            <div v-for="connector in store.connectors" :key="connector.name" class="connector-row">
              <span>{{ connector.name }}</span>
              <small>{{ connector.input }}</small>
            </div>
          </div>
        </div>
      </section>

      <section v-if="page === 'library'" class="content-grid library-grid">
        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Profiles</p>
              <h2>来源库</h2>
            </div>
            <Users class="panel-icon" />
          </div>
          <div class="data-list">
            <button
              v-for="profile in store.profiles"
              :key="profile.id"
              type="button"
              class="data-row selectable"
              :class="{ selected: store.selectedProfileId === profile.id }"
              @click="store.selectedProfileId = profile.id"
            >
              <span>
                <strong>{{ profile.display_name || profile.handle || profile.id }}</strong>
                <small>{{ profile.platform }} · {{ profile.profile_url }}</small>
              </span>
              <ChevronRight class="icon" />
            </button>
            <p v-if="store.profiles.length === 0" class="empty">还没有采集过 Profile。</p>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Corpus IR</p>
              <h2>语料集合</h2>
            </div>
          </div>
          <div class="data-list">
            <div v-for="corpus in store.corpora" :key="corpus.id" class="data-row">
              <span>
                <strong>{{ corpus.title }}</strong>
                <small>{{ corpus.goal || '自主发现' }} · {{ countDocuments(corpus) }} docs</small>
              </span>
              <code>{{ shortId(corpus.id) }}</code>
            </div>
            <p v-if="store.corpora.length === 0" class="empty">还没有 Corpus。</p>
          </div>
        </div>
      </section>

      <section v-if="page === 'distill'" class="content-grid distill-grid">
        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Distillation Layer</p>
              <h2>蒸馏工作台</h2>
            </div>
            <BrainCircuit class="panel-icon" />
          </div>

          <div class="form-grid">
            <label class="field">
              <span>目标 Profile</span>
              <select v-model="store.selectedProfileId">
                <option value="">请选择</option>
                <option v-for="profile in store.profiles" :key="profile.id" :value="profile.id">
                  {{ profile.display_name || profile.handle || profile.id }}
                </option>
              </select>
            </label>
            <label class="field">
              <span>语料上限</span>
              <input v-model.number="distillForm.itemLimit" type="number" min="1" max="1000" />
            </label>
            <label class="field wide">
              <span>自主发现目标</span>
              <input v-model="distillForm.goal" placeholder="例如：提取投研拆解方法论" />
            </label>
          </div>

          <div class="action-row">
            <button type="button" class="secondary-button" :disabled="store.loading" @click="buildCorpus">
              <Layers class="icon" />
              生成 Corpus
            </button>
            <button type="button" class="primary-button" :disabled="store.loading" @click="discoverCapability">
              <Sparkles class="icon" />
              自主发现能力
            </button>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Custom Capability</p>
              <h2>定向能力提取</h2>
            </div>
          </div>
          <div class="form-grid">
            <label class="field wide">
              <span>想蒸馏的能力</span>
              <input v-model="extractForm.focus" placeholder="例如：中国 A 股产业链相关性挖掘" />
            </label>
            <label class="field">
              <span>能力类型</span>
              <input v-model="extractForm.capabilityType" />
            </label>
            <label class="field wide">
              <span>能力 Schema JSON</span>
              <textarea v-model="extractForm.schema" rows="6" placeholder='{"outputs":["chain","companies","evidence"]}' />
            </label>
          </div>
          <div class="action-row">
            <button type="button" class="primary-button" :disabled="store.loading" @click="extractCapability">
              <Wand2 class="icon" />
              提取定向能力
            </button>
          </div>
        </div>
      </section>

      <section v-if="page === 'evidence'" class="content-grid evidence-grid">
        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Capability Review</p>
              <h2>证据审阅</h2>
            </div>
            <ShieldCheck class="panel-icon" />
          </div>
          <div class="data-list">
            <button
              v-for="capability in store.capabilities"
              :key="capability.id"
              type="button"
              class="data-row selectable"
              :class="{ selected: store.selectedCapabilityId === capability.id }"
              @click="store.selectedCapabilityId = capability.id"
            >
              <span>
                <strong>{{ capability.name }}</strong>
                <small>{{ capability.type }} · {{ capability.review_state }} · {{ percent(capability.confidence) }}</small>
              </span>
            </button>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Evidence Links</p>
              <h2>{{ selectedCapability?.name || '未选择能力' }}</h2>
            </div>
          </div>
          <p class="summary-text">{{ selectedCapability?.summary || '选择一个 Capability 后查看证据链。' }}</p>
          <div class="evidence-list">
            <article v-for="item in selectedEvidence" :key="String(item.id)" class="evidence-item">
              <p>{{ item.quote || '无摘录' }}</p>
              <small>{{ item.source_url || item.doc_id || item.item_id }}</small>
            </article>
          </div>
          <div class="review-box">
            <textarea v-model="reviewNotes" rows="3" placeholder="审阅备注" />
            <div class="action-row">
              <button type="button" class="secondary-button" @click="reviewCapability('needs_revision')">
                <CircleAlert class="icon" />
                需修订
              </button>
              <button type="button" class="primary-button" @click="reviewCapability('approved')">
                <CheckCircle2 class="icon" />
                通过
              </button>
            </div>
          </div>
        </div>
      </section>

      <section v-if="page === 'packs'" class="content-grid pack-grid">
        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Skill Packaging</p>
              <h2>Skill 库</h2>
            </div>
            <PackageCheck class="panel-icon" />
          </div>
          <div class="action-row">
            <button type="button" class="secondary-button" :disabled="!store.selectedCapabilityId" @click="createPack">
              <PackagePlus class="icon" />
              从选中能力创建 Pack
            </button>
          </div>
          <div class="data-list">
            <button
              v-for="pack in store.packs"
              :key="pack.id"
              type="button"
              class="data-row selectable"
              :class="{ selected: store.selectedPackId === pack.id }"
              @click="store.selectedPackId = pack.id"
            >
              <span>
                <strong>{{ pack.title }}</strong>
                <small>{{ pack.version }} · {{ pack.target_surfaces?.join(', ') }}</small>
              </span>
              <code>{{ shortId(pack.id) }}</code>
            </button>
          </div>
        </div>

        <div class="panel compact">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Export</p>
              <h2>多平台导出</h2>
            </div>
          </div>
          <label class="field">
            <span>目标平台</span>
            <select v-model="exportForm.target">
              <option value="codex-skill">Codex Skill</option>
              <option value="openai-skill">OpenAI Skill</option>
              <option value="claude-skill">Claude Skill</option>
              <option value="claude-project-bundle">Claude Project Bundle</option>
              <option value="json-ir">JSON IR</option>
            </select>
          </label>
          <label class="field">
            <span>输出目录</span>
            <input v-model="exportForm.outputRoot" placeholder="默认 outputs" />
          </label>
          <button type="button" class="primary-button full" :disabled="store.loading || !store.selectedPackId" @click="exportPack">
            <Download class="icon" />
            导出选中 Pack
          </button>
          <div class="export-list">
            <div v-for="artifact in store.exports.slice(0, 6)" :key="artifact.id" class="export-row">
              <span>{{ artifact.target }}</span>
              <small>{{ artifact.path }}</small>
            </div>
          </div>
        </div>
      </section>

      <section v-if="page === 'jobs'" class="panel full-panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Task Registry</p>
            <h2>任务与日志</h2>
          </div>
          <Clock3 class="panel-icon" />
        </div>
        <div class="job-table">
          <div class="job-row header">
            <span>任务</span>
            <span>状态</span>
            <span>阶段</span>
            <span>进度</span>
            <span>更新时间</span>
          </div>
          <div v-for="job in store.jobs" :key="job.id" class="job-row">
            <span><strong>{{ job.type }}</strong><small>{{ shortId(job.id) }}</small></span>
            <span :class="['pill', job.status]">{{ job.status }}</span>
            <span>{{ job.phase || '-' }}</span>
            <span>{{ job.progress }}%</span>
            <span>{{ job.updated_at || '-' }}</span>
          </div>
        </div>
      </section>

      <section v-if="page === 'settings'" class="content-grid settings-grid">
        <div class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Model/API</p>
              <h2>模型与接口设置</h2>
            </div>
            <Settings2 class="panel-icon" />
          </div>
          <div class="form-grid">
            <label class="field wide">
              <span>LLM Base URL</span>
              <input v-model="settingsForm.llm_base_url" />
            </label>
            <label class="field">
              <span>LLM Model</span>
              <input v-model="settingsForm.llm_model" />
            </label>
            <label class="field wide">
              <span>LLM API Key</span>
              <input v-model="settingsForm.llm_api_key" type="password" placeholder="留空则不修改" />
            </label>
            <label class="field wide">
              <span>Vision Base URL</span>
              <input v-model="settingsForm.vision_base_url" />
            </label>
            <label class="field">
              <span>Vision Model</span>
              <input v-model="settingsForm.vision_model" />
            </label>
            <label class="field wide">
              <span>ASR Base URL</span>
              <input v-model="settingsForm.asr_base_url" />
            </label>
            <label class="field">
              <span>ASR Model</span>
              <input v-model="settingsForm.asr_model" />
            </label>
          </div>
          <div class="action-row">
            <button type="button" class="primary-button" @click="saveSettings">
              <Save class="icon" />
              保存设置
            </button>
          </div>
        </div>

        <div class="panel compact">
          <div class="metric-stack">
            <div class="metric">
              <span>Profiles</span>
              <strong>{{ store.profiles.length }}</strong>
            </div>
            <div class="metric">
              <span>Capabilities</span>
              <strong>{{ store.capabilities.length }}</strong>
            </div>
            <div class="metric">
              <span>Skill Packs</span>
              <strong>{{ store.packs.length }}</strong>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Database,
  Download,
  Layers,
  Library,
  ListPlus,
  PackageCheck,
  PackagePlus,
  Play,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users,
  Wand2
} from 'lucide-vue-next'
import { useWorkbenchStore } from './stores/workbench'

type PageKey = 'source' | 'library' | 'distill' | 'evidence' | 'packs' | 'jobs' | 'settings'

const store = useWorkbenchStore()
const page = ref<PageKey>('source')
const reviewNotes = ref('')

const sourceForm = reactive({
  source: '',
  platform: '',
  max_items: 50,
  include_comments: false,
  include_media: true,
  deep: true
})

const distillForm = reactive({
  goal: '提取可复用的研究与决策方法论',
  itemLimit: 200
})

const extractForm = reactive({
  focus: '中国公司产业链相关性挖掘',
  capabilityType: 'chain_relevance_mining',
  schema: '{\n  "outputs": ["chain", "companies", "evidence", "confidence"]\n}'
})

const exportForm = reactive({
  target: 'codex-skill',
  outputRoot: ''
})

const settingsForm = reactive({
  llm_base_url: '',
  llm_api_key: '',
  llm_model: '',
  vision_base_url: '',
  vision_api_key: '',
  vision_model: '',
  asr_base_url: '',
  asr_api_key: '',
  asr_model: ''
})

const navItems = computed(() => [
  { key: 'source', label: '新建数据源', icon: Database, badge: '' },
  { key: 'library', label: '来源库', icon: Library, badge: String(store.profiles.length || '') },
  { key: 'distill', label: '蒸馏工作台', icon: BrainCircuit, badge: '' },
  { key: 'evidence', label: '证据审阅', icon: ShieldCheck, badge: String(store.capabilities.length || '') },
  { key: 'packs', label: 'Skill 库', icon: PackageCheck, badge: String(store.packs.length || '') },
  { key: 'jobs', label: '任务与日志', icon: Clock3, badge: String(store.jobs.length || '') },
  { key: 'settings', label: '模型/API 设置', icon: Settings2, badge: '' }
] as const)

const currentTitle = computed(() => navItems.value.find((item) => item.key === page.value)?.label || '')
const apiPath = computed(() => (store.health?.home as string) || 'http://127.0.0.1:8080')
const selectedCapability = computed(() => store.selectedCapability)
const selectedEvidence = computed(() => selectedCapability.value?.evidence || [])

onMounted(async () => {
  await store.refreshAll()
  hydrateSettingsForm()
})

watch(
  () => store.settings,
  () => hydrateSettingsForm()
)

function hydrateSettingsForm() {
  const settings = store.settings
  if (!settings) return
  settingsForm.llm_base_url = settings.llm?.base_url || ''
  settingsForm.llm_model = settings.llm?.model || ''
  settingsForm.vision_base_url = settings.vision?.base_url || ''
  settingsForm.vision_model = settings.vision?.model || ''
  settingsForm.asr_base_url = settings.asr?.base_url || ''
  settingsForm.asr_model = settings.asr?.model || ''
}

function sourcePayload() {
  return {
    source: sourceForm.source,
    platform: sourceForm.platform || null,
    max_items: sourceForm.max_items,
    include_comments: sourceForm.include_comments,
    include_media: sourceForm.include_media,
    deep: sourceForm.deep
  }
}

async function collectNow() {
  await store.collectSource(sourcePayload())
}

async function queueCollect() {
  await store.queueJob('collect_source', sourcePayload())
}

async function buildCorpus() {
  await store.buildCorpus(distillForm.goal, distillForm.itemLimit)
}

async function discoverCapability() {
  await store.discoverCapability(distillForm.goal, distillForm.itemLimit)
}

async function extractCapability() {
  await store.extractCapability(
    extractForm.focus,
    extractForm.capabilityType,
    distillForm.itemLimit,
    extractForm.schema
  )
}

async function reviewCapability(state: string) {
  await store.reviewCapability(state, reviewNotes.value)
}

async function createPack() {
  await store.createPack(['codex-skill', 'openai-skill', 'claude-skill'])
}

async function exportPack() {
  await store.exportPack(exportForm.target, exportForm.outputRoot)
}

async function saveSettings() {
  await store.saveSettings(settingsForm)
  settingsForm.llm_api_key = ''
  settingsForm.vision_api_key = ''
  settingsForm.asr_api_key = ''
}

function shortId(value: string) {
  return value ? `${value.slice(0, 8)}...` : ''
}

function percent(value: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function countDocuments(corpus: { metadata?: Record<string, any> }) {
  return corpus.metadata?.counts?.documents || 0
}
</script>

<style scoped>
.workbench-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: var(--sa-sidebar) minmax(0, 1fr);
}

.sidebar {
  height: 100vh;
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--sa-surface) 92%, var(--sa-surface-strong));
  border-right: 1px solid var(--sa-border);
}

.brand {
  height: var(--sa-header);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  border-bottom: 1px solid var(--sa-border);
}

.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(135deg, var(--sa-accent), #1f6f8b);
  font-weight: 800;
}

.brand p,
.sidebar-footer p {
  margin: 0;
  font-weight: 750;
}

.brand span,
.sidebar-footer small,
.data-row small,
.connector-row small,
.export-row small,
.job-row small {
  color: var(--sa-text-muted);
  font-size: 12px;
}

.nav-list {
  flex: 1;
  overflow: auto;
  padding: 12px;
}

.nav-item {
  width: 100%;
  min-height: 42px;
  display: grid;
  grid-template-columns: 20px 1fr auto;
  align-items: center;
  gap: 10px;
  border: 1px solid transparent;
  border-radius: var(--sa-radius-sm);
  padding: 9px 10px;
  color: var(--sa-text-muted);
  background: transparent;
  text-align: left;
}

.nav-item.active,
.nav-item:hover {
  color: var(--sa-text);
  background: var(--sa-surface);
  border-color: var(--sa-border);
}

.nav-item.active {
  box-shadow: inset 3px 0 0 var(--sa-accent);
}

.nav-item small {
  min-width: 22px;
  text-align: right;
  color: var(--sa-accent-strong);
}

.sidebar-footer {
  min-height: 68px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  border-top: 1px solid var(--sa-border);
}

.status-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--sa-yellow);
}

.status-dot.ok {
  background: var(--sa-green);
}

.main-panel {
  min-width: 0;
}

.topbar {
  height: var(--sa-header);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 0 24px;
  background: color-mix(in srgb, var(--sa-bg) 86%, #fff);
  border-bottom: 1px solid var(--sa-border);
}

.eyebrow {
  margin: 0 0 5px;
  color: var(--sa-accent-strong);
  font-size: 12px;
  font-weight: 750;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  letter-spacing: 0;
}

h1 {
  font-size: 22px;
}

h2 {
  font-size: 17px;
}

.topbar-actions,
.action-row,
.toggle-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.content-grid {
  display: grid;
  gap: 16px;
  padding: 18px;
}

.source-grid,
.distill-grid,
.evidence-grid,
.pack-grid,
.settings-grid,
.library-grid {
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
}

.panel {
  min-width: 0;
  background: var(--sa-surface);
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius);
  box-shadow: var(--sa-shadow);
  padding: 16px;
}

.panel.compact {
  align-self: start;
}

.full-panel {
  margin: 18px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-icon {
  width: 24px;
  height: 24px;
  color: var(--sa-accent);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.field {
  display: grid;
  gap: 6px;
}

.field.wide {
  grid-column: 1 / -1;
}

.field span {
  color: var(--sa-text-muted);
  font-size: 12px;
  font-weight: 700;
}

input,
select,
textarea {
  width: 100%;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-sm);
  padding: 9px 10px;
  color: var(--sa-text);
  background: var(--sa-surface-soft);
  outline: none;
}

textarea {
  resize: vertical;
  min-height: 96px;
}

input:focus,
select:focus,
textarea:focus {
  border-color: var(--sa-accent);
  box-shadow: 0 0 0 3px rgba(212, 107, 44, 0.14);
}

.toggle-row {
  margin: 14px 0;
  color: var(--sa-text-muted);
}

.toggle-row label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.primary-button,
.secondary-button,
.ghost-button {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: var(--sa-radius-sm);
  padding: 8px 12px;
  font-weight: 750;
}

.primary-button {
  border: 1px solid var(--sa-accent-strong);
  background: var(--sa-accent);
  color: #fff;
}

.secondary-button,
.ghost-button {
  border: 1px solid var(--sa-border);
  background: var(--sa-surface-soft);
  color: var(--sa-text);
}

.full {
  width: 100%;
}

.connector-list,
.data-list,
.evidence-list,
.export-list {
  display: grid;
  gap: 8px;
}

.connector-row,
.data-row,
.evidence-item,
.export-row {
  min-width: 0;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-sm);
  padding: 10px;
  background: var(--sa-surface-soft);
}

.data-row {
  align-items: center;
}

.data-row.selectable {
  width: 100%;
  color: inherit;
  text-align: left;
}

.data-row.selected {
  border-color: var(--sa-accent);
  background: color-mix(in srgb, var(--sa-accent) 9%, #fff);
}

.data-row span,
.export-row {
  min-width: 0;
}

.data-row strong,
.data-row small,
.export-row small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

code {
  color: var(--sa-accent-strong);
  font-size: 12px;
}

.empty,
.summary-text {
  color: var(--sa-text-muted);
  line-height: 1.65;
}

.evidence-item {
  display: block;
}

.evidence-item p {
  margin: 0 0 8px;
  line-height: 1.55;
}

.review-box {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.metric-stack {
  display: grid;
  gap: 10px;
}

.metric {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-sm);
  padding: 12px;
  background: var(--sa-surface-soft);
}

.metric span {
  color: var(--sa-text-muted);
}

.metric strong {
  font-size: 24px;
}

.job-table {
  display: grid;
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius);
}

.job-row {
  display: grid;
  grid-template-columns: 1.4fr 0.8fr 0.8fr 0.6fr 1.2fr;
  gap: 12px;
  align-items: center;
  min-height: 48px;
  padding: 9px 12px;
  background: var(--sa-surface);
}

.job-row.header {
  min-height: 40px;
  color: var(--sa-text-muted);
  font-size: 12px;
  font-weight: 800;
  background: var(--sa-surface-strong);
}

.pill {
  width: fit-content;
  border-radius: 999px;
  padding: 4px 8px;
  color: #fff;
  background: var(--sa-text-muted);
  font-size: 12px;
}

.pill.succeeded {
  background: var(--sa-green);
}

.pill.running,
.pill.queued {
  background: var(--sa-blue);
}

.pill.failed {
  background: var(--sa-red);
}

.toast {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 999px;
  padding: 7px 10px;
  font-size: 12px;
  font-weight: 750;
}

.toast.ok {
  color: var(--sa-green);
  background: rgba(15, 138, 95, 0.1);
}

.toast.error {
  color: var(--sa-red);
  background: rgba(192, 54, 44, 0.1);
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1180px) {
  .source-grid,
  .distill-grid,
  .evidence-grid,
  .pack-grid,
  .settings-grid,
  .library-grid {
    grid-template-columns: 1fr;
  }
}
</style>
