import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 渠道共享页·全局 agent 切换联动契约。
 *
 * 同一根因（2026-10-04 渠道管理页缺陷的兄弟命中点）：本页走 useAgentPage，
 * store 变化会更新页内 agentId，但取数只挂在 onMounted —— 全局切换器
 * （AgentSwitcher，autoNavigate 默认 false）换 agent 后 URL 不变、组件不重挂载，
 * 共享列表停在旧 agent。
 *
 * 修复契约：接 useAgentPage 既有 onAgentChange 回调（MemoryPage 同款模式），
 * agentId 变化即重取；守卫边界：store 自动兜底选中与同值切换不得触发重复取数。
 */

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('vue-router', () => ({
  // 形状须含 query：useAgentPage 的 route→store 同步 watch 读 route.query.agentId
  useRoute: () => ({ params: { agentId: '216fb777' }, query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

import { request } from '@/api'
import { useAgentStore } from '@/stores/agents'
import ContextChannelPage from '../ContextChannelPage.vue'

const AGENTS = [
  { id: '216fb777', name: '凯蒂', status: 'active' },
  { id: 'kai', name: '凯', status: 'active' },
]

const messages = {
  'zh-CN': {
    common: { save: '保存', cancel: '取消', success: '成功', error: '错误' },
    nav: { agentchannel: '渠道配置', agentchannelsharing: '渠道共享' },
    contextChannel: {
      title: '渠道共享', desc: '', sharingEnabled: '共享开关', enabled: '已共享', disabled: '未共享', test: '测试',
    },
  },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(ContextChannelPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassPanel: { template: '<div><slot/></div>' },
        GlassCard: { template: '<div><slot/></div>' },
        GlassButton: { template: '<button><slot/></button>' },
        AgentPageTabs: { props: ['tabs'], template: '<div class="page-tabs"/>' },
        'a-switch': { props: ['checked'], emits: ['change'], template: '<button/>' },
        'a-tag': { template: '<span><slot/></span>' },
        'a-button': { template: '<button><slot/></button>' },
      },
    },
  })
}

describe('ContextChannelPage — 全局 agent 切换联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(request.get as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({
      data: { config: { enabled: false }, channels: [] },
    })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('全局切换器换 agent → 共享列表按新 agent 重取', async () => {
    mountPage()
    await flushPromises()
    const getsAfterMount = (request.get as unknown as { mock: { calls: unknown[][] } }).mock.calls.length

    const store = useAgentStore()
    store.setCurrentAgent('kai')
    await flushPromises()

    expect((request.get as unknown as { mock: { calls: unknown[][] } }).mock.calls.length).toBeGreaterThan(getsAfterMount)
  })

  it('同值切换不触发重复取数', async () => {
    mountPage()
    await flushPromises()
    const getsAfterMount = (request.get as unknown as { mock: { calls: unknown[][] } }).mock.calls.length

    const store = useAgentStore()
    store.setCurrentAgent('216fb777')
    await flushPromises()

    expect((request.get as unknown as { mock: { calls: unknown[][] } }).mock.calls.length).toBe(getsAfterMount)
  })
})
