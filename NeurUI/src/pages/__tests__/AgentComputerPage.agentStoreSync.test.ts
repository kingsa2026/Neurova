import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 电脑操作页·全局 agent 切换联动契约（T-21 同根因扫荡，工单集 §45.2）。
 *
 * 缺陷：`agentId` 非响应式解构 + 仅 onMounted 截屏——全局切换器换人后，页面
 * 停留旧 agent 的屏幕画面与操作目标。修复契约：换 useAgentPage——身份跟随
 * store，onAgentChange 重新截取新 agent 的画面（页面主体即该 agent 的屏幕）。
 */

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { agentId: 'kai' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/api/modules/computer', () => ({
  screenshot: vi.fn().mockResolvedValue({ data: { url: '' } }),
  click: vi.fn().mockResolvedValue({}),
  type: vi.fn().mockResolvedValue({}),
  scroll: vi.fn().mockResolvedValue({}),
  navigate: vi.fn().mockResolvedValue({}),
  extractPage: vi.fn().mockResolvedValue({ data: {} }),
  smartClick: vi.fn().mockResolvedValue({}),
  smartType: vi.fn().mockResolvedValue({}),
  shell: vi.fn().mockResolvedValue({ data: {} }),
}))

import { screenshot } from '@/api/modules/computer'
import { useAgentStore } from '@/stores/agents'
import AgentComputerPage from '../AgentComputerPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  'a-input': { template: '<input/>' },
  'a-input-number': { template: '<input/>' },
  'a-select': { props: ['value', 'options'], template: '<select/>' },
  'a-select-option': { template: '<option/>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentComputerPage, { global: { plugins: [i18n], stubs } })
}

describe('AgentComputerPage — 全局 agent 切换联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('初挂载按路由身份截屏', async () => {
    mountPage()
    await flushPromises()

    expect(screenshot).toHaveBeenCalledWith('kai')
  })

  it('全局切换器换 agent → 按新 agent 重新截屏', async () => {
    mountPage()
    await flushPromises()

    useAgentStore().setCurrentAgent('k2')
    await flushPromises()

    expect(screenshot).toHaveBeenCalledWith('k2')
  })
})
