/**
 * Agent 切换联动总闸 — 同根因页面防回归（2026-09-15，与人格页 bug 同族）
 *
 * 根因同 AgentPersonalityPage.agentSwitch.test.ts：页面用 useAgentPage() 取
 * agent 级数据，但未接 onAgentChange，切换 agent 后不重拉/链接不更新。
 * 覆盖：KnowledgeGraphPage / SleepStatusPage / SleepSettingsPage（数据重拉）、
 *       ContextChannelPage（页签链接随 agent 更新）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'

let pageAgentId: ReturnType<typeof ref<string>> | undefined
let registeredOnAgentChange: ((id: string) => void) | undefined

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: (options?: { onAgentChange?: (id: string) => void }) => {
    registeredOnAgentChange = options?.onAgentChange
    pageAgentId ??= ref('agent-A')
    return {
      agentId: pageAgentId,
      currentAgent: ref({ name: 'A' }),
      agentLoading: ref(false),
    }
  },
}))

vi.mock('@/api', () => ({
  request: {
    get: vi.fn(),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('@/stores/app', () => ({
  useAppStore: () => ({ isDark: false }),
}))

vi.mock('@/composables/usePolling', () => ({
  usePolling: () => ({ loading: ref(false), start: vi.fn(), stop: vi.fn(), poll: vi.fn() }),
}))

vi.mock('@/composables/useAPI', () => ({
  useMutation: () => ({ mutate: vi.fn(), loading: ref(false), pending: ref(false) }),
}))

vi.mock('@/api/modules/sleep', () => ({
  unwrapSleep: (res: any) => res?.data ?? null,
  getSleepStatus: vi.fn().mockResolvedValue({ data: { sleep_phase: 'idle' } }),
  getDreams: vi.fn().mockResolvedValue({ data: { items: [] } }),
  getSleepInsights: vi.fn().mockResolvedValue({ data: [] }),
  getMergeConflicts: vi.fn().mockResolvedValue({ data: [] }),
  getSleepSettings: vi.fn().mockResolvedValue({ data: {} }),
  updateSleepSettings: vi.fn().mockResolvedValue({ data: {} }),
  wakeUp: vi.fn().mockResolvedValue({ data: {} }),
  putToSleep: vi.fn().mockResolvedValue({ data: {} }),
  applyInsight: vi.fn().mockResolvedValue({ data: {} }),
  resolveConflict: vi.fn().mockResolvedValue({ data: {} }),
}))

vi.mock('vue-echarts', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({ name: 'VChart', props: ['option'], render: () => h('div', { class: 'vchart-stub' }) }),
  }
})

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }
})

import KnowledgeGraphPage from '@/pages/KnowledgeGraphPage.vue'
import SleepStatusPage from '@/pages/SleepStatusPage.vue'
import SleepSettingsPage from '@/pages/SleepSettingsPage.vue'
import ContextChannelPage from '@/pages/ContextChannelPage.vue'
import { request } from '@/api'
import * as sleepApi from '@/api/modules/sleep'
import AgentPageTabs from '@/components/AgentPageTabs.vue'

const globalStubs = {
  GlassPanel: { props: ['variant', 'glow'], template: '<div><slot/></div>' },
  GlassCard: { props: ['title'], template: '<div class="glass-card"><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['loading', 'variant', 'size', 'disabled', 'danger'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  GlassStatCard: { props: ['label', 'value', 'emoji'], template: '<div/>' },
  VChart: { template: '<div class="vchart-stub"/>' },
  'v-chart': { template: '<div class="vchart-stub"/>' },
  AgentPageTabs: { props: ['tabs'], template: '<div class="page-tabs"/>' },
  'a-tabs': { template: '<div><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div><slot/></div>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div/>' },
  'a-progress': { props: ['percent'], template: '<div/>' },
  'a-tag': { props: ['color'], template: '<span><slot/></span>' },
  'a-slider': { props: ['value', 'min', 'max', 'disabled'], template: '<div/>' },
  'a-input': { props: ['value', 'placeholder'], template: '<input/>' },
  'a-input-search': { props: ['value', 'placeholder'], template: '<input/>' },
  'a-select': { props: ['value', 'options'], template: '<div><slot/></div>' },
  'a-select-option': { props: ['value'], template: '<div><slot/></div>' },
  'a-switch': { props: ['checked'], template: '<div/>' },
  'a-form': { props: ['model'], template: '<div><slot/></div>' },
  'a-form-item': { props: ['label'], template: '<div><slot/></div>' },
  'a-modal': { props: ['open', 'visible', 'title'], template: '<div><slot/></div>' },
  'a-table': { props: ['dataSource', 'columns'], template: '<div/>' },
  'a-button': { props: ['type'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
  'a-card': { props: ['title'], template: '<div><slot/></div>' },
  'a-tooltip': { props: ['title'], template: '<div><slot/></div>' },
  'a-badge': { props: ['status'], template: '<div><slot/></div>' },
  'a-descriptions': { template: '<div><slot/></div>' },
  'a-descriptions-item': { props: ['label'], template: '<div><slot/></div>' },
  'a-radio-group': { props: ['value'], template: '<div><slot/></div>' },
  'a-radio': { props: ['value'], template: '<label><slot/></label>' },
  'a-checkbox': { props: ['checked'], template: '<label><slot/></label>' },
  'a-list': { template: '<div><slot/></div>' },
  'a-list-item': { template: '<div><slot/></div>' },
  'a-collapse': { template: '<div><slot/></div>' },
  'a-collapse-panel': { props: ['header'], template: '<div><slot/></div>' },
  'a-divider': { template: '<div/>' },
  'a-avatar': { props: ['src', 'shape'], template: '<div/>' },
  'a-space': { template: '<div><slot/></div>' },
  'a-statistic': { props: ['title', 'value'], template: '<div/>' },
  'a-steps': { props: ['current', 'items'], template: '<div/>' },
  'a-alert': { props: ['message', 'type', 'showIcon'], template: '<div/>' },
  'a-popconfirm': { props: ['title'], template: '<div><slot/></div>' },
  'a-row': { template: '<div><slot/></div>' },
  'a-col': { props: ['span'], template: '<div><slot/></div>' },
  'a-textarea': { props: ['value'], template: '<textarea/>' },
}

function mountPage(component: any) {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', fallbackLocale: 'zh-CN', messages: { 'zh-CN': {} } })
  return mount(component, { global: { plugins: [i18n], stubs: globalStubs } })
}

async function switchToAgentB() {
  pageAgentId!.value = 'agent-B'
  registeredOnAgentChange?.('agent-B')
  await flushPromises()
}

describe('Agent 切换联动总闸（同根因页面族）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pageAgentId = undefined
    registeredOnAgentChange = undefined
    vi.mocked(request.get).mockResolvedValue({ data: { nodes: [], edges: [] } } as any)
    vi.mocked(sleepApi.getSleepStatus).mockResolvedValue({ data: { sleep_phase: 'idle' } } as any)
    vi.mocked(sleepApi.getDreams).mockResolvedValue({ data: { items: [] } } as any)
    vi.mocked(sleepApi.getSleepInsights).mockResolvedValue({ data: [] } as any)
    vi.mocked(sleepApi.getMergeConflicts).mockResolvedValue({ data: [] } as any)
    vi.mocked(sleepApi.getSleepSettings).mockResolvedValue({ data: {} } as any)
  })

  it('KnowledgeGraphPage：注册 onAgentChange 且切换后按新 agent 重拉图谱', async () => {
    mountPage(KnowledgeGraphPage)
    await flushPromises()
    expect(registeredOnAgentChange, '图谱页未接 onAgentChange，切换 agent 不刷新').toBeTypeOf('function')
    vi.mocked(request.get).mockClear()
    await switchToAgentB()
    expect(request.get).toHaveBeenCalledWith('/knowledge-graph/agent-B/knowledge-graph')
  })

  it('SleepStatusPage：切换 agent 后睡眠状态/梦境/洞察/冲突按新 agent 重拉', async () => {
    mountPage(SleepStatusPage)
    await flushPromises()
    expect(registeredOnAgentChange, '睡眠状态页未接 onAgentChange').toBeTypeOf('function')
    vi.mocked(sleepApi.getSleepStatus).mockClear()
    vi.mocked(sleepApi.getDreams).mockClear()
    await switchToAgentB()
    expect(sleepApi.getSleepStatus).toHaveBeenCalledWith('agent-B')
    expect(sleepApi.getDreams).toHaveBeenCalledWith('agent-B', expect.anything())
  })

  it('SleepSettingsPage：切换 agent 后设置与冲突按新 agent 重拉', async () => {
    mountPage(SleepSettingsPage)
    await flushPromises()
    expect(registeredOnAgentChange, '睡眠设置页未接 onAgentChange').toBeTypeOf('function')
    vi.mocked(sleepApi.getSleepSettings).mockClear()
    await switchToAgentB()
    expect(sleepApi.getSleepSettings).toHaveBeenCalledWith('agent-B')
  })

  it('ContextChannelPage：页签链接随 agent 切换更新（不残留旧 agent 路径）', async () => {
    vi.mocked(request.get).mockImplementation((async (url: string) =>
      url.endsWith('/available-channels')
        ? { data: { channels: [] } }
        : { data: { config: { enabled: false } } }) as any)
    const wrapper = mountPage(ContextChannelPage)
    await flushPromises()
    const tabs = () => wrapper.findComponent(AgentPageTabs).props('tabs') as Array<{ to: string }>
    expect(tabs()[0].to).toContain('/agent/agent-A/')
    pageAgentId!.value = 'agent-B'
    await flushPromises()
    expect(tabs()[0].to).toContain('/agent/agent-B/')
  })
})
