import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 系统渠道页·agent 选择器契约（同根因第二命中点）。
 *
 * 本页曾与 Agent 渠道页**逐字重复**同一行错映射
 * （`agentOptions.map((o) => ({ value: o.id, label: o.name }))`）：两页共享
 * 字段目录 `config/channelFields.ts`，选择器却没共享同一份映射。
 * 现两页共用 `config/agentOptions.ts` 的 `buildAgentSelectOptions`。
 *
 * 本页初值是硬编码 `'default'`（取证报告 §2.4 的反证入口），故这里钉的是
 * **选项具备真身份**——存量配置挂在 default 名下时，用户至少能主动切回真 agent。
 */

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn(),
  createChannelConfig: vi.fn(),
  testChannelConfig: vi.fn(),
  getIngressStats: vi.fn(),
  restartChannelAdapter: vi.fn(),
  clearChannelQueue: vi.fn(),
  checkChannelConflicts: vi.fn(),
  listPluginChannelSchemas: vi.fn(),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn(),
  updateNegativeScreenConfig: vi.fn(),
  testNegativeScreenPush: vi.fn(),
  deleteNegativeScreenConfig: vi.fn(),
  getPushStatistics: vi.fn(),
}))

import { api } from '@/api'
import {
  listChannelConfigs, getIngressStats, listPluginChannelSchemas,
  checkChannelConflicts,
} from '@/api/modules/channel-configs'
import { getNegativeScreenConfig, getPushStatistics } from '@/api/modules/negative-screen'

import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'

const AGENTS = [
  { id: '216fb777', name: '凯蒂', status: 'active' },
  { id: 'kai', name: '凯', status: 'active' },
]

const messages = {
  'zh-CN': {
    common: { search: '搜索', cancel: '取消', save: '保存' },
    channel: {
      integration: '渠道集成', integrationDesc: '管理消息渠道', all: '全部', builtin: '内置',
      customChannel: '自定义渠道', noChannels: '暂无渠道', connected: '已连接', enabled: '已启用',
      disabled: '未启用', enable: '启用', disable: '禁用', configure: '配置', configureDesc: '配置渠道参数',
      test: '测试', testSuccess: '测试通过', testFailed: '测试失败', configSaved: '配置已保存',
      configSaveFailed: '保存失败', commonSettings: '通用设置', platformSettings: '平台设置',
      ingressQueue: '入站队列', ingressPending: '待处理', ingressProcessing: '处理中',
      ingressDead: '死信', ingressProcessed: '已处理', conflictCheck: '冲突检测',
      defaultAgent: '默认智能体', restart: '重启', clearQueue: '清空队列', scanAuth: '扫码授权',
      getQrcode: '获取二维码', scanHint: '提示', scanAuthSuccess: '成功', scanExpired: '过期',
      scanFailed: '失败', wecomMode: '模式', wecomModeAibot: '机器人', wecomModeEnterprise: '企业',
    },
    settings: { negativeScreen: '负一屏推送' },
    negativeScreen: {
      title: '负一屏推送设置', enable: '启用', enableHint: '', authCode: '授权码', authCodePlaceholder: '',
      authCodeConfigured: '', getAuthCodeSteps: '', step1: '', step2: '', step3: '', pushUrl: 'URL',
      pushUrlPlaceholder: '', pushUrlHint: '', testPush: '测试推送', testSuccess: '', testFailed: '',
      deleteConfig: '删除', statsTitle: '统计', totalNotifications: '总数', pushedCount: '已推送',
      failedCount: '失败', successRate: '成功率', configSaved: '', saveFailed: '', configDeleted: '',
      deleteFailed: '', testPushSuccess: '', testPushFailed: '', testPushTaskName: '', testPushContent: '',
      testPushResult: '', loadNegScreenConfigFailed: '', saveNegScreenConfigFailed: '',
      loadPushStatsFailed: '',
    },
    ui: { chXiaoyi: '小艺', chDingtalk: '钉钉', chFeishu: '飞书', chWechat: '微信', chWecom: '企业微信', chYuanbao: '元宝' },
    nav: { showToolMessages: '工具', showThinking: '思考', streamMode: '流式', privateChatStrategy: '私',
      groupChatStrategy: '群', requireMention: '@', region: '区域', groupShareSession: '共享',
      tokenFile: 'Token', messageMerge: '合并', dingtalkAppKey: 'k', dingtalkAppSecret: 's',
      mediaDirectory: '媒体', replyAtSender: '@', instantConfirm: '即时', disableDm: '', disableGroup: '',
      receiveBotMessages: '' },
  },
}

/** a-select 假体把 options 原样渲成 option 节点（读的是真选项数组）。 */
const agentSelectStub = {
  props: ['options', 'value'],
  emits: ['update:value', 'change'],
  template: `<select class="agent-select" :value="value"
    @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
    <option v-for="opt in (options || [])" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</option>
  </select>`,
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(ChannelIntegrationPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': agentSelectStub,
        'a-spin': { template: '<div><slot/></div>' },
        'a-tag': { template: '<span><slot/></span>' },
        'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
        'a-form': { template: '<form><slot/></form>' },
        'a-form-item': { props: ['label'], template: '<div><label>{{ label }}</label><slot/></div>' },
        'a-switch': { template: '<button/>' },
        'a-input': { template: '<input/>' },
        'a-input-password': { template: '<input type="password"/>' },
        'a-descriptions': { template: '<div><slot/></div>' },
        'a-descriptions-item': { props: ['label'], template: '<div><b>{{ label }}</b><slot/></div>' },
        GlassInput: { template: '<input/>' },
        NegativeScreenSettings: { template: '<div class="neg-settings"/>' },
      },
    },
  })
}

describe('ChannelIntegrationPage — agent 选择器携带真身份', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: AGENTS })
        return Promise.resolve({ data: [] })
      })
    ;(listChannelConfigs as any).mockResolvedValue([])
    ;(getIngressStats as any).mockResolvedValue({ enabled: false })
    ;(listPluginChannelSchemas as any).mockResolvedValue({ data: { schemas: [] } })
    ;(checkChannelConflicts as any).mockResolvedValue({ conflicts: [] })
    ;(getNegativeScreenConfig as any).mockResolvedValue({ enabled: false })
    ;(getPushStatistics as any).mockResolvedValue({ code: 0, data: {} })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('选项里出现真智能体，不是空白行', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const options = wrapper.findAll('.agent-select option').map((o) => ({
      value: o.attributes('value'),
      label: o.text(),
    }))
    expect(options).toContainEqual({ value: '216fb777', label: '凯蒂' })
    expect(options).toContainEqual({ value: 'kai', label: '凯' })
    expect(options.some((o) => !o.value || o.value === 'undefined')).toBe(false)
  })
})
