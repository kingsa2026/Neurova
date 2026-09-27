import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 渠道页·agent 选择器契约。
 *
 * 缺陷回归（2026-09-28 取证报告 Bug A）：本页与系统渠道页曾按 `o.id / o.name`
 * 读 agentOptions，而生产端（stores/agents.ts）给出的元素是 `{label, value, isWorkflow}`
 * —— 两个键名都是 undefined，于是选择器渲染出无文字空白行；选中即
 * `agentId = undefined`，`listChannelConfigs(undefined)` 不发 agent_id 参数，
 * 后端 Query 默认值把它兜成 default：**用户以为在给 X 配飞书，实际写进了 default 的表**。
 *
 * 本文件**不得** mock `useAgentStore` 的 agentOptions（旧布局用例把 store mock 成空数组，
 * `.map()` 对空数组恒等，错键名因此永远不会显形）：改用真 pinia store + mock `GET /agents`。
 */

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { agentId: '216fb777' } }) }))
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

/** a-select 假体把 options 原样渲成 <option> 节点，并保留 v-model 回写。 */
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

/** 选择器选项的 {value,label} 读数（从真实渲染出的 option 节点取，不看内部变量）。 */
function selectOptions(wrapper: ReturnType<typeof mountPage>) {
  return wrapper.findAll('.agent-select option').map((o) => ({
    value: o.attributes('value'),
    label: o.text(),
  }))
}

describe('AgentChannelPage — agent 选择器携带真身份', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: AGENTS })
        return Promise.resolve({ data: [] })
      })
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([])
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('选项里出现真智能体的 id 与名字，不是空白行', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const options = selectOptions(wrapper)
    expect(options).toContainEqual({ value: '216fb777', label: '凯蒂' })
    expect(options).toContainEqual({ value: 'kai', label: '凯' })
    expect(options.some((o) => !o.value || o.value === 'undefined')).toBe(false)
  })

  it('列表按路由来的 agent 身份取数，不静默落到 default', async () => {
    mountPage()
    await flushPromises()

    expect(listChannelConfigs).toHaveBeenCalledWith('216fb777')
  })
})
