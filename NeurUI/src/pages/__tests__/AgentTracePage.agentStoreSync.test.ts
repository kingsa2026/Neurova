import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 链路追踪页·全局 agent 切换联动契约（T-21 同根因扫荡，工单集 §45.2）。
 *
 * 缺陷：`agentId` 是 `route.params.agentId` 的非响应式解构且取数只挂 onMounted
 * ——全局切换器（AgentSwitcher autoNavigate 默认 false）只写 store 不产生路由
 * 变化，router-view 的 :key 也不重挂载，页面永远停在旧 agent 的链路与统计。
 *
 * 修复契约：换 useAgentPage 既有机制——身份跟随 store，onAgentChange 单点重取。
 */

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { agentId: 'kai' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/api/modules/trace', () => ({
  listTraces: vi.fn().mockResolvedValue({ data: { items: [] } }),
  getTraceStats: vi.fn().mockResolvedValue({ data: {} }),
  getTraceDetail: vi.fn().mockResolvedValue({ data: {} }),
}))

import { listTraces, getTraceStats } from '@/api/modules/trace'
import { useAgentStore } from '@/stores/agents'
import AgentTracePage from '../AgentTracePage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  'a-list': { template: '<div><slot/></div>' },
  'a-list-item': { template: '<div><slot/></div>' },
  'a-progress': { props: ['percent'], template: '<div/>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-table': { props: ['dataSource'], template: '<div/>' },
  'a-tag': { template: '<span class="page-tag"><slot/></span>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentTracePage, { global: { plugins: [i18n], stubs } })
}

describe('AgentTracePage — 全局 agent 切换联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('初挂载按路由身份取数', async () => {
    mountPage()
    await flushPromises()

    expect(listTraces).toHaveBeenCalledWith('kai')
    expect(getTraceStats).toHaveBeenCalledWith('kai')
  })

  it('全局切换器换 agent → 链路与统计按新 agent 重取', async () => {
    mountPage()
    await flushPromises()

    useAgentStore().setCurrentAgent('k2')
    await flushPromises()

    expect(listTraces).toHaveBeenCalledWith('k2')
    expect(getTraceStats).toHaveBeenCalledWith('k2')
  })
})
