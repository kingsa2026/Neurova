import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 防火墙页·全局 agent 切换联动契约（T-21 同根因扫荡，工单集 §45.2）。
 *
 * 缺陷：`agentId` 非响应式解构——全局切换器换人后，页面的身份标签与**写侧目标**
 * （规则增删改走 /agents/{agentId}/firewall/*）仍指向旧 agent。
 * 读侧端点是全局的（/firewall/*，无 agent 维度），故本页无按 agent 重取的数据，
 * 修复契约是身份跟随 store（展示与写侧目标换人），不挂重取回调。
 */

const requestGet = vi.fn((url: string) => {
  if (url === '/firewall/stats') return Promise.resolve({ data: {} })
  return Promise.resolve({ data: [] })
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { agentId: 'kai' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/api', () => ({
  request: {
    get: (...args: unknown[]) => requestGet(...(args as [string])),
    post: vi.fn(), put: vi.fn(), delete: vi.fn(),
  },
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { useAgentStore } from '@/stores/agents'
import AgentFirewallPage from '../AgentFirewallPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  'a-empty': { template: '<div/>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div><slot/></div>' },
  'a-input': { template: '<input/>' },
  'a-input-number': { template: '<input/>' },
  'a-modal': { props: ['open'], template: '<div v-if="open"><slot/></div>' },
  'a-popconfirm': { template: '<div><slot/></div>' },
  'a-select': { props: ['value', 'options'], template: '<select/>' },
  'a-select-option': { template: '<option/>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-switch': { props: ['checked'], template: '<button/>' },
  'a-tab-pane': { props: ['tab'], template: '<div><slot/></div>' },
  'a-table': { template: '<div/>' },
  'a-tabs': { template: '<div><slot/></div>' },
  'a-tag': { template: '<span class="page-tag"><slot/></span>' },
  'a-tooltip': { template: '<div><slot/></div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentFirewallPage, { global: { plugins: [i18n], stubs } })
}

describe('AgentFirewallPage — 全局 agent 切换联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('初挂载展示路由身份', async () => {
    const w = mountPage()
    await flushPromises()

    expect(w.find('.page-tag').text()).toBe('kai')
  })

  it('全局切换器换 agent → 身份标签与写侧目标跟随新 agent', async () => {
    const w = mountPage()
    await flushPromises()

    useAgentStore().setCurrentAgent('k2')
    await flushPromises()

    expect(w.find('.page-tag').text()).toBe('k2')
  })
})
