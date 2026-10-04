import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 轨迹页·全局 agent 切换联动契约（T-21 同根因扫荡，工单集 §45.2）。
 *
 * 缺陷与修复契约同 AgentTracePage（同一批复制的非响应式解构 + onMounted 单取数）：
 * 换 useAgentPage——身份跟随 store，onAgentChange 单点重取。
 */

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { agentId: 'kai' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/api/modules/trace', () => ({
  listTraces: vi.fn().mockResolvedValue({ data: {} }),
  getTraceStats: vi.fn().mockResolvedValue({ data: {} }),
  getTraceDetail: vi.fn().mockResolvedValue({ data: {} }),
}))

import { listTraces } from '@/api/modules/trace'
import { useAgentStore } from '@/stores/agents'
import AgentTrajectoryPage from '../AgentTrajectoryPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  'a-descriptions': { template: '<div><slot/></div>' },
  'a-descriptions-item': { props: ['label'], template: '<div><slot/></div>' },
  'a-empty': { template: '<div/>' },
  'a-list': { template: '<div><slot/></div>' },
  'a-list-item': { template: '<div><slot/></div>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-timeline': { template: '<div><slot/></div>' },
  'a-timeline-item': { template: '<div><slot/></div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentTrajectoryPage, { global: { plugins: [i18n], stubs } })
}

describe('AgentTrajectoryPage — 全局 agent 切换联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('初挂载按路由身份取数', async () => {
    mountPage()
    await flushPromises()

    expect(listTraces).toHaveBeenCalledWith('kai')
  })

  it('全局切换器换 agent → 轨迹按新 agent 重取', async () => {
    mountPage()
    await flushPromises()

    useAgentStore().setCurrentAgent('k2')
    await flushPromises()

    expect(listTraces).toHaveBeenCalledWith('k2')
  })
})
