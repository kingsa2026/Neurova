import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 渠道页·空态必须**可归因**（Issue #290 取证报告 §2.7-4 验收线）。
 *
 * ## 缺陷
 *
 * 本页把「这个 agent 确实没配过任何渠道」与「配置读不到」渲染成**同一个样子**：
 * 整页卡片一律「未启用」。用户读到的结论是"我的配置全没了"，而真相可能是
 * 配置挂在别的 agent 名下（存量全在 `default`，而侧栏进的是 `/agent/<真 id>/channel`）。
 *
 * 这正是本 bug 被拖了 6 天没人定位到落点的原因：两种空在页面上不可区分，
 * 用户没有任何线索可循，只能报告"配置全部失效"。
 *
 * ## 判据
 *
 * 按路由 agent 取数为空、且该 agent 不是 `default` 时：
 * - 必须给出**点名**的说明（当前 agent 尚无配置 + 存量可能在默认视图下）；
 * - 必须给出一键切到默认视图的入口（用户能自己找回配置，无需猜）。
 *
 * 反向控制：`default` 视图下不得出现该提示（那里本来就是空没有别的可能），
 * 以及有配置时不得出现。
 */

const routeState = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { reactive } = require('vue')
  return { current: reactive({ params: { agentId: '216fb777' } as Record<string, string> }) }
})
const routerPush = vi.fn((target: unknown) => {
  const params = (target as { params?: Record<string, string> })?.params
  if (params?.agentId) routeState.current.params.agentId = String(params.agentId)
  return Promise.resolve()
})

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('vue-router', () => ({
  useRoute: () => routeState.current,
  useRouter: () => ({ push: routerPush }),
}))
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([]),
  createChannelConfig: vi.fn().mockResolvedValue({}),
  deleteChannelConfig: vi.fn().mockResolvedValue({}),
  getChannelQrcode: vi.fn().mockResolvedValue({ qrcode_img: '', poll_token: '' }),
  getChannelQrcodeStatus: vi.fn().mockResolvedValue({ status: 'waiting', credentials: {} }),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
  updateNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  testNegativeScreenPush: vi.fn().mockResolvedValue({ success: true }),
  deleteNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  getPushStatistics: vi.fn().mockResolvedValue({ code: 0, data: {} }),
}))

import { api } from '@/api'
import { listChannelConfigs } from '@/api/modules/channel-configs'
import AgentChannelPage from '../AgentChannelPage.vue'

const AGENTS = [
  { id: '216fb777', name: '凯蒂', status: 'active' },
  { id: 'kai', name: '凯', status: 'active' },
]

// 用**真语言包**而不是手写桩：手写桩与 `zh-CN.ts` 各写一份键，桩里补了键
// 而真语言包漏了也照样绿 —— 那正是"判据看着咬合、实际没咬住"的老路。
import zhCN from '@/i18n/locales/zh-CN'

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentChannelPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': { props: ['options', 'value'], template: '<select class="agent-select"><option v-for="o in (options||[])" :key="String(o.value)" :value="String(o.value)">{{ o.label }}</option></select>' },
        'a-spin': { template: '<div><slot/></div>' },
        'a-tag': { template: '<span><slot/></span>' },
        'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
        'a-alert': { props: ['message', 'description'], template: '<div class="ant-alert">{{ message }}{{ description }}</div>' },
        'a-modal': { props: ['title'], template: '<div><slot/></div>' },
        'a-form': { template: '<form><slot/></form>' },
        'a-form-item': { props: ['label', 'required'], template: '<div><label>{{ label }}</label><slot/></div>' },
        'a-switch': { template: '<button/>' },
        'a-input': { template: '<input/>' },
        'a-input-number': { template: '<input/>' },
        NegativeScreenSettings: { template: '<div class="neg-settings"/>' },
      },
    },
  })
}

describe('AgentChannelPage — 空态可归因', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    routeState.current.params.agentId = '216fb777'
    vi.clearAllMocks()
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: AGENTS })
        return Promise.resolve({ data: [] })
      })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('按路由 agent 取数为空时给出点名空态与切换入口', async () => {
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()

    const hint = wrapper.find('[data-testid="empty-attribution"]')
    expect(hint.exists(), '空态没有任何归因说明——用户只能读成"配置全没了"').toBe(true)
    // 断言的就是真语言包的原文（含插值）：点名当前身份，用户才知道自己在看谁
    expect(hint.text()).toContain('216fb777 尚无渠道配置')
    expect(hint.text()).toContain('配置可能在默认视图下')
  })

  it('入口把用户带到默认视图（identity 走路由）', async () => {
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('[data-testid="switch-to-default"]').trigger('click')
    await flushPromises()

    expect(routeState.current.params.agentId).toBe('default')
  })

  it('反向控制：该 agent 有配置时不出现空态归因', async () => {
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([
      { channel_type: 'feishu', enabled: true, connected: true, extra: {} },
    ])
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(false)
  })

  it('反向控制：default 视图下不出现（那里本就是唯一可能的位置）', async () => {
    routeState.current.params.agentId = 'default'
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(false)
  })
})
