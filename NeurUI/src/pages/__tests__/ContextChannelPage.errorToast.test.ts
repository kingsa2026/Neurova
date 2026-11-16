/**
 * 3.6-15 审计收口（R5）：handleToggle/handleTest 的 catch 分支注释说
 * handled 实际未处理任何错误——补 uiMessage.error 如实透出（开关 :checked
 * 绑定后端值，失败自动回弹，用户至少能看到失败提示）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, ref } from 'vue'

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: ref('agent-1'), currentAgent: ref({ name: 'A' }), agentLoading: ref(false) }),
}))

const { apiMock } = vi.hoisted(() => {
  const apiMock = { get: vi.fn(), post: vi.fn(), put: vi.fn() }
  return { apiMock }
})

vi.mock('@/api', () => ({ default: apiMock, api: apiMock, request: apiMock }))

vi.mock('ant-design-vue', async () => {
  const { message } = await vi.importActual<any>('ant-design-vue')
  return { message: { ...message, error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() } }
})

import ContextChannelPage from '../ContextChannelPage.vue'
import { message } from 'ant-design-vue'
import { clearDedupeCache } from '@/utils/message'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, fallbackWarn: false, messages: { 'zh-CN': zhCN as never } })

const passthrough = { template: '<div><slot /></div>' }
const antStubs = Object.fromEntries(
  ['a-switch', 'a-tag', 'a-spin', 'a-empty', 'a-tooltip'].map((name) => [name, passthrough]),
)

function mountPage() {
  return mount(ContextChannelPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassPanel: passthrough, GlassCard: passthrough, GlassButton: passthrough,
        AgentPageTabs: passthrough, ...antStubs,
      },
    },
  })
}

function sharingPayload() {
  return [
    { data: { code: 0, data: { config: { enabled: true } } } },
    { data: { code: 0, data: { channels: [{ type: 'feishu', label: '飞书', is_shared: true }] } } },
  ]
}

describe('ContextChannelPage — 3.6-15 catch 透出错误', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    clearDedupeCache()
    let call = 0
    apiMock.get.mockImplementation(() => {
      const payload = sharingPayload()
      return Promise.resolve(payload[Math.min(call++, payload.length - 1)])
    })
  })

  it('共享开关落库失败 → message.error（旧实现 catch 注释说 handled 实际静默）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    apiMock.post.mockRejectedValue(new Error('boom'))
    await (wrapper.vm as any).handleToggle('feishu', false)
    await flushPromises()
    expect(message.error).toHaveBeenCalled()
  })

  it('测试连接失败 → message.error', async () => {
    const wrapper = mountPage()
    await flushPromises()
    apiMock.post.mockRejectedValue(new Error('boom'))
    await (wrapper.vm as any).handleTest('feishu')
    await flushPromises()
    expect(message.error).toHaveBeenCalled()
    expect((wrapper.vm as any).testingId).toBeNull()
  })
})
