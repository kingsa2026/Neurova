import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 渠道页·agent 切换必须以**路由为唯一事实源**（Issue #290 未闭环项②）。
 *
 * ## 缺陷（2026-09-28 取证报告登记，未修）
 *
 * `@change="fetchConfigs"` 只改本地 `agentId` ref，URL 仍是进入时的旧 agent。
 * 后果分三层，逐层都比"显示不同步"更重：
 *
 * 1. **刷新即回退**：用户切到「凯蒂」配完渠道，F5 一次回到路由里的旧 agent，
 *    页面看起来"配置又没了"——而配置其实在「凯蒂」名下，只是当前视图读的是别人；
 * 2. **可分享性丧失**：URL 不再表达当前身份，"把这个 agent 的渠道页发给我"做不到；
 * 3. **写错归属**：`saveConfig` / `removeChannel` 都按 `agentId.value` 落盘，
 *    而浏览器前进后退、外部链接跳转都会用**路由**重算本页 —— 两个事实源说出
 *    不同身份时，用户按屏幕认知操作、系统按另一个身份写。
 *
 * ## 判据
 *
 * 切换选择器后：
 * - 路由被推到**新 agent** 的渠道页（URL 成为事实源）；
 * - 列表按新身份重新取数（不是只改本地变量）；
 * - 从路由进入（`/agent/X/channel`）时，页面身份与路由一致。
 */

/**
 * 路由替身：`params` 是**响应式**的，`push` 会真的改它 —— 与真路由同形。
 * 若替身把 push 记成「被调用」却不改 params，判据就只咬得住「有没有调 push」，
 * 咬不住「切换后页面身份是否真的跟着走」，正是本用例要防的那种半截判据。
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

const messages = {
  'zh-CN': {
    common: { disabled: '禁用', delete: '删除', enable: '启用', yes: '是', no: '否', success: '成功', error: '错误' },
    channel: {
      agentChannels: '渠道配置', agentChannelsDesc: '', defaultAgent: '默认智能体', configure: '配置',
      connected: '已连接', enabled: '已启用', enabledNotConnected: '已启用未连接', noChannels: '暂无',
      configSaveFailed: '保存失败', removeChannelConfirm: '删除 {name}？',
      scanAuth: '扫码授权', getQrcode: '获取二维码', scanHint: '提示',
      scanAuthSuccess: '成功', scanExpired: '过期', scanFailed: '失败',
      enabledSection: '已激活', disabledSection: '未激活', botPrefixLabel: '机器人前缀', notSet: '未设置',
      wecomMode: '模式', wecomModeAibot: '机器人', wecomModeEnterprise: '企业',
    },
    settings: { negativeScreen: '负一屏推送' },
    nav: {
      showToolMessages: '工具', showThinking: '思考', streamMode: '流式', privateChatStrategy: '私',
      groupChatStrategy: '群', requireMention: '@', region: '区域', feishuChina: '飞书', larkInternational: 'Lark',
      groupShareSession: '共享', tokenFile: 'Token', messageMerge: '合并', dingtalkAppKey: 'k', dingtalkAppSecret: 's',
      mediaDirectory: '媒体', replyAtSender: '@', instantConfirm: '即时', disableDm: '', disableGroup: '', receiveBotMessages: '',
    },
    ui: { chXiaoyi: '小艺', chDingtalk: '钉钉', chFeishu: '飞书', chWechat: '微信', chWecom: '企业微信', chYuanbao: '元宝' },
  },
}

const agentSelectStub = {
  props: ['options', 'value'],
  emits: ['update:value', 'change'],
  template: `<select class="agent-select"
    :value="value"
    @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
    <option v-for="opt in (options || [])" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</option>
  </select>`,
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(AgentChannelPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': agentSelectStub,
        'a-spin': { template: '<div><slot/></div>' },
        'a-tag': { template: '<span><slot/></span>' },
        'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
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

describe('AgentChannelPage — 切换 agent 以路由为唯一事实源', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    routeState.current.params.agentId = '216fb777'
    vi.clearAllMocks()
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: AGENTS })
        return Promise.resolve({ data: [] })
      })
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([])
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('切换 agent 后路由被推到新身份的渠道页（刷新不丢身份）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('.agent-select').setValue('kai')
    await flushPromises()

    expect(routerPush).toHaveBeenCalled()
    expect(routeState.current.params.agentId).toBe('kai')
  })

  it('切换后按新身份重新取数，不只改本地变量', async () => {
    const wrapper = mountPage()
    await flushPromises()
    ;(listChannelConfigs as unknown as { mockClear: () => void }).mockClear()

    await wrapper.find('.agent-select').setValue('kai')
    await flushPromises()

    expect(listChannelConfigs).toHaveBeenCalledWith('kai')
  })
})
