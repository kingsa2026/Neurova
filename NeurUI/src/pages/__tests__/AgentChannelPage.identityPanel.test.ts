import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 渠道身份绑定面板挂在渠道页上的接线判据（工单 2026-10-10 批 4b）。
 *
 * 面板自己的语义在 `components/__tests__/ChannelIdentityPanel.test.ts`，这一格只管三件事，
 * 都是"组件做对了但没接上"才会暴露的形态：
 * 1. 取数按**路由里的 agent**（本页身份的唯一事实源是路由，不是本地 ref）；
 * 2. 发码只列该 agent **已配置**的渠道——没配 bot 的渠道里不会有消息进来，
 *    在那里发码等于发一张永远用不掉的码；
 * 3. 一台什么都没配的实例上，**整页装配**必须把"为什么点不动"交到用户眼前
 *    （`configuredChannelTypes` 由页面算出并传下去，组件那侧读不到这一维）。
 */

const routeState = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { reactive } = require('vue')
  return { current: reactive({ params: { agentId: '216fb777' } as Record<string, string> }) }
})

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('vue-router', () => ({
  useRoute: () => routeState.current,
  useRouter: () => ({ push: vi.fn(() => Promise.resolve()) }),
}))
const listChannelIdentityBindings = vi.fn().mockResolvedValue({ bindings: [] })
const listObservedChannelSenders = vi.fn().mockResolvedValue({ senders: [] })
const listMyChannelIdentityBindings = vi.fn().mockResolvedValue({ user_id: 'u1', bindings: [] })
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([]),
  createChannelConfig: vi.fn().mockResolvedValue({}),
  deleteChannelConfig: vi.fn().mockResolvedValue({}),
  getChannelQrcode: vi.fn().mockResolvedValue({ qrcode_img: '', poll_token: '' }),
  getChannelQrcodeStatus: vi.fn().mockResolvedValue({ status: 'waiting', credentials: {} }),
  listChannelIdentityBindings: (...a: unknown[]) => listChannelIdentityBindings(...a),
  issueChannelBindingCode: vi.fn().mockResolvedValue({ code: '123456' }),
  revokeChannelIdentityBinding: vi.fn().mockResolvedValue({ revoked: true }),
  listObservedChannelSenders: (...a: unknown[]) => listObservedChannelSenders(...a),
  listMyChannelIdentityBindings: (...a: unknown[]) => listMyChannelIdentityBindings(...a),
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
// 用真语言包：手写桩与 zh-CN.ts 各写一份键，桩补了而真包漏了照样绿
import zhCN from '@/i18n/locales/zh-CN'

const AGENTS = [{ id: '216fb777', name: '凯蒂', status: 'active' }]

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentChannelPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': {
          props: ['options', 'value'],
          template: '<select class="sel"><option v-for="o in (options||[])" :key="String(o.value)" :value="String(o.value)">{{ o.label }}</option></select>',
        },
        'a-spin': { template: '<div><slot/></div>' },
        'a-tag': { template: '<span><slot/></span>' },
        'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
        'a-modal': { props: ['title'], template: '<div><slot/></div>' },
        'a-form': { template: '<form><slot/></form>' },
        'a-form-item': { props: ['label'], template: '<div><slot/></div>' },
        'a-switch': { template: '<button/>' },
        'a-input': { template: '<input/>' },
        'a-input-number': { template: '<input/>' },
        NegativeScreenSettings: { template: '<div class="neg-settings"/>' },
      },
    },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  routeState.current.params.agentId = '216fb777'
  vi.clearAllMocks()
  listChannelIdentityBindings.mockResolvedValue({ bindings: [] })
  // `clearAllMocks()` 清的是调用记录，**不清 `mockResolvedValue`**——上一格喂过 feishu
  // 就会漏到下一格。这里把"一台什么都没配的实例"钉回默认，谁要非空自己就地覆盖。
  ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void })
    .mockResolvedValue([])
  ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
    .mockImplementation((url: string) => {
      if (url === '/agents') return Promise.resolve({ data: AGENTS })
      return Promise.resolve({ data: [] })
    })
})
afterEach(() => { document.body.innerHTML = '' })

describe('AgentChannelPage — 绑定面板的接线', () => {
  it('面板在页上，且按路由 agent 取数（不是硬编码 default）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="identity-panel"]').exists(),
      '渠道页上没有绑定面板——用户只能去数据库里手工写绑定行').toBe(true)
    expect(listChannelIdentityBindings).toHaveBeenCalledWith('216fb777')
  })

  it('发码只列该 agent 已配置的渠道', async () => {
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void })
      .mockResolvedValue([{ channel_type: 'feishu', enabled: true, connected: true, extra: {} }])
    const wrapper = mountPage()
    await flushPromises()

    const options = wrapper.find('[data-testid="identity-channel-select"]')
      .findAll('option').map((o) => o.text())
    expect(options).toEqual(['feishu'])
    // 有得选就不该再解释「为什么不能点」：那句是禁用态的解释，不是常驻说明文
    expect(wrapper.find('[data-testid="identity-no-configured-channel"]').exists()).toBe(false)
  })

  it('零已配置渠道 ⇒ 页面组合层就把「为什么点不动」交到用户眼前', async () => {
    // 夹具默认就是「一台没配任何渠道的实例」——浏览器实跑撞到的正是这一形。
    // 组件那侧的格子证不了这一维：`configuredChannelTypes` 是**页面**算出来传下去的，
    // 只有整页装配才走得到「下拉空 + 按钮永久禁用」那条真实路径。
    const wrapper = mountPage()
    await flushPromises()

    const hint = wrapper.find('[data-testid="identity-no-configured-channel"]')
    expect(hint.exists(), '整页装配下禁用态仍是一块哑巴').toBe(true)
    expect(hint.text(), '提示必须来自真语言包（手写桩补了键、真包漏了照样白屏）')
      .toContain('还没有已配置的渠道')
  })
})
