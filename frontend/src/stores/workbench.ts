import { defineStore } from 'pinia'
import { apiGet, apiPost } from '../api/client'

export interface Profile {
  id: string
  platform: string
  profile_url: string
  handle?: string
  display_name?: string
  updated_at?: string
}

export interface Job {
  id: string
  type: string
  status: string
  progress: number
  phase?: string
  result?: Record<string, unknown>
  error?: string
  updated_at?: string
}

export interface Corpus {
  id: string
  profile_id: string
  title: string
  goal?: string
  metadata?: Record<string, any>
}

export interface Capability {
  id: string
  corpus_id: string
  profile_id: string
  name: string
  type: string
  summary: string
  review_state: string
  confidence: number
  evidence?: Array<Record<string, any>>
  workflow?: string[]
  principles?: string[]
}

export interface SkillPack {
  id: string
  capability_id: string
  profile_id: string
  skill_id: string
  title: string
  version: string
  target_surfaces?: string[]
}

export const useWorkbenchStore = defineStore('workbench', {
  state: () => ({
    health: null as Record<string, unknown> | null,
    settings: null as Record<string, any> | null,
    connectors: [] as Array<Record<string, string>>,
    profiles: [] as Profile[],
    jobs: [] as Job[],
    corpora: [] as Corpus[],
    capabilities: [] as Capability[],
    packs: [] as SkillPack[],
    exports: [] as Array<Record<string, any>>,
    selectedProfileId: '',
    selectedCapabilityId: '',
    selectedPackId: '',
    loading: false,
    error: '',
    notice: ''
  }),
  getters: {
    selectedProfile(state): Profile | undefined {
      return state.profiles.find((item) => item.id === state.selectedProfileId)
    },
    selectedCapability(state): Capability | undefined {
      return state.capabilities.find((item) => item.id === state.selectedCapabilityId)
    },
    selectedPack(state): SkillPack | undefined {
      return state.packs.find((item) => item.id === state.selectedPackId)
    }
  },
  actions: {
    async refreshAll() {
      this.loading = true
      this.error = ''
      try {
        const [health, settings, connectors, profiles, jobs, corpora, capabilities, packs, exports] =
          await Promise.all([
            apiGet<Record<string, unknown>>('/health'),
            apiGet<Record<string, any>>('/settings'),
            apiGet<Array<Record<string, string>>>('/api/v1/sources/connectors'),
            apiGet<Profile[]>('/profiles'),
            apiGet<Job[]>('/jobs'),
            apiGet<Corpus[]>('/api/v1/corpora'),
            apiGet<Capability[]>('/api/v1/capabilities'),
            apiGet<SkillPack[]>('/api/v1/packs'),
            apiGet<Array<Record<string, any>>>('/api/v1/exports')
          ])
        this.health = health
        this.settings = settings
        this.connectors = connectors
        this.profiles = profiles
        this.jobs = jobs
        this.corpora = corpora
        this.capabilities = capabilities
        this.packs = packs
        this.exports = exports
        if (!this.selectedProfileId && profiles[0]) this.selectedProfileId = profiles[0].id
        if (!this.selectedCapabilityId && capabilities[0]) this.selectedCapabilityId = capabilities[0].id
        if (!this.selectedPackId && packs[0]) this.selectedPackId = packs[0].id
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
    async collectSource(payload: Record<string, unknown>) {
      await this.runAction('采集完成', async () => {
        await apiPost('/api/v1/sources:collect', payload)
        await this.refreshAll()
      })
    },
    async queueJob(type: string, payload: Record<string, unknown>) {
      await this.runAction('任务已创建', async () => {
        await apiPost('/api/v1/jobs', { type, payload })
        await this.refreshAll()
      })
    },
    async buildCorpus(goal: string, itemLimit: number) {
      if (!this.selectedProfileId) throw new Error('请选择 Profile')
      await this.runAction('Corpus 已生成', async () => {
        await apiPost('/api/v1/corpora', {
          profile_id: this.selectedProfileId,
          goal,
          item_limit: itemLimit
        })
        await this.refreshAll()
      })
    },
    async discoverCapability(goal: string, itemLimit: number) {
      if (!this.selectedProfileId) throw new Error('请选择 Profile')
      await this.runAction('能力已自主发现', async () => {
        const capability = await apiPost<Capability>(
          `/api/v1/profiles/${this.selectedProfileId}/capabilities:discover`,
          { goal, item_limit: itemLimit }
        )
        this.selectedCapabilityId = capability.id
        await this.refreshAll()
      })
    },
    async extractCapability(focus: string, capabilityType: string, itemLimit: number, schemaText: string) {
      if (!this.selectedProfileId) throw new Error('请选择 Profile')
      const schema = schemaText.trim() ? JSON.parse(schemaText) : {}
      await this.runAction('定向能力已提取', async () => {
        const capability = await apiPost<Capability>('/api/v1/capabilities:extract', {
          profile_id: this.selectedProfileId,
          focus,
          capability_type: capabilityType,
          item_limit: itemLimit,
          schema
        })
        this.selectedCapabilityId = capability.id
        await this.refreshAll()
      })
    },
    async reviewCapability(reviewState: string, notes: string) {
      if (!this.selectedCapabilityId) throw new Error('请选择 Capability')
      await this.runAction('审阅状态已更新', async () => {
        await apiPost(`/api/v1/capabilities/${this.selectedCapabilityId}:review`, {
          review_state: reviewState,
          notes
        })
        await this.refreshAll()
      })
    },
    async createPack(targetSurfaces: string[]) {
      if (!this.selectedCapabilityId) throw new Error('请选择 Capability')
      await this.runAction('Skill Pack 已创建', async () => {
        const pack = await apiPost<SkillPack>(`/api/v1/capabilities/${this.selectedCapabilityId}/packs`, {
          target_surfaces: targetSurfaces
        })
        this.selectedPackId = pack.id
        await this.refreshAll()
      })
    },
    async exportPack(target: string, outputRoot: string) {
      if (!this.selectedPackId) throw new Error('请选择 Skill Pack')
      await this.runAction('导出完成', async () => {
        await apiPost(`/api/v1/packs/${this.selectedPackId}/exports`, {
          target,
          output_root: outputRoot || null
        })
        await this.refreshAll()
      })
    },
    async saveSettings(payload: Record<string, unknown>) {
      await this.runAction('设置已保存', async () => {
        await apiPost('/settings', payload)
        await this.refreshAll()
      })
    },
    async runAction(message: string, action: () => Promise<void>) {
      this.loading = true
      this.error = ''
      this.notice = ''
      try {
        await action()
        this.notice = message
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    }
  }
})
