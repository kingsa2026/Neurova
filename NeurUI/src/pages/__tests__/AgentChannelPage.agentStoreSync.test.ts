import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 渠道页·全局 agent 切换联动契约。
 *
 * 缺陷（2026-10-04 用户报告"渠道管理页面不随 agent 切换改变"）：
 * MainLayout 的 AgentSwitcher 未配 autoNavigate（默认 false）也不处理 @select，
 * 切换只写 `agentStore.currentAgentId`、不产生路由变化；而本页 agentId 以
 * 路由为唯一事实源（route.params.agentId），watch(agentId) 因此永远不触发，
 * 屏幕停在旧 agent 的渠道列表。
 *
 * 修复契约：store 变化必须经由页面唯一的身份写入口（推路由）落地——
 * 与页内选择器 switchAgent 同一条通路，不另开第二条取数路径。
 * 守卫边界：store 的**自动兜底选中**（loadAgents 对空 currentAgentId 的默认
 * 选中，prev=null）不是用户切换，不得据此改写 URL，否则分享链接/刷新后
 * 会被强行带去兜底 agent。
 */

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  // 可响应路由替身：push 后 params 生效，模拟真路由的参数落地，
  // 使页面内 watch(agentId) 能走完"推路由 → 取数"全链路。
  const __testRoute = reactive({ params: { agentId: '216fb777' } })
  const __testRouterPush = vi.fn((to: { params?: { agentId?: string } }) => {
    const next = to?.params?.agentId
    if (next) __testRoute.params.agentId = String(next)
  })
  return {
    useRoute: () => __testRoute,
    useRouter: () => ({ push: __testRouterPush }),
    __testRoute,
    __testRouterPush,
  }
})

vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([]),
  createChannelConfig: vi.fn().mockResolvedValue({}),
  deleteChannelConfig: vi.fn().mockResolvedValue({}),
  // 渠道身份绑定面板（工单 2026-10-10 批 4b）：桩面必须跟着真模块面长——
  // 缺键时面板会静默走进错误分支，页面判据看着全绿却没人真取过数。
  listChannelIdentityBindings: vi.fn().mockResolvedValue({ bindings: [] }),
  listObservedChannelSenders: vi.fn().mockResolvedValue({ senders: [] }),
  listMyChannelIdentityBindings: vi.fn().mockResolvedValue({ user_id: 'u1', bindings: [] }),
  issueChannelBindingCode: vi.fn().mockResolvedValue({ code: '123456', command: '绑定 123456', expires_in: 600, bound_user_id: 'u1' }),
  revokeChannelIdentityBinding: vi.fn().mockResolvedValue({ revoked: true }),
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
import * as vueRouterModule from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import AgentChannelPage from '../AgentChannelPage.vue'

// mock 工厂附加的替身句柄不在 vue-router 的真类型里，经形状断言取用
const routerMock = vueRouterModule as unknown as {
  __testRoute: { params: { agentId: string } }
  __testRouterPush: ReturnType<typeof vi.fn>
}
const __testRoute = routerMock.__testRoute
const __testRouterPush = routerMock.__testRouterPush

/** 真 store 的响应源：两个已注册智能体（与登记表实测同名同 ID 形状）。 */
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

describe('AgentChannelPage — 全局 agent 切换联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    __testRoute.params.agentId = '216fb777'
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: AGENTS })
        return Promise.resolve({ data: [] })
      })
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([])
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('store 自动兜底选中（prev=null）不改写 URL——分享链接不被带跑', async () => {
    mountPage()
    await flushPromises()

    expect(__testRouterPush).not.toHaveBeenCalled()
    expect(__testRoute.params.agentId).toBe('216fb777')
  })

  it('全局切换器换 agent → 推路由到新 agent，列表随路由取数', async () => {
    mountPage()
    await flushPromises()
    expect(listChannelConfigs).toHaveBeenCalledWith('216fb777')

    const store = useAgentStore()
    store.setCurrentAgent('kai')
    await flushPromises()

    // 身份唯一写入口是路由：store 变化经推路由落地
    expect(__testRouterPush).toHaveBeenCalledWith({ name: 'AgentChannel', params: { agentId: 'kai' } })
    // 路由落地后，既有的取数链路拿到新身份
    expect(listChannelConfigs).toHaveBeenCalledWith('kai')
  })

  it('切换到与路由相同的 agent → 不推路由不重复取数', async () => {
    mountPage()
    await flushPromises()
    const callsAfterMount = (listChannelConfigs as unknown as { mock: { calls: unknown[][] } }).mock.calls.length

    const store = useAgentStore()
    store.setCurrentAgent('216fb777')
    await flushPromises()

    expect(__testRouterPush).not.toHaveBeenCalled()
    expect((listChannelConfigs as unknown as { mock: { calls: unknown[][] } }).mock.calls.length).toBe(callsAfterMount)
  })
})
