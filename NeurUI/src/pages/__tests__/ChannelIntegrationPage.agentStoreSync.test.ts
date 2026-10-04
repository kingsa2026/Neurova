import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 系统渠道页（消息渠道，/channels）·全局 agent 切换联动契约。
 *
 * 缺陷（2026-10-04 用户截图取证）：侧栏全局切换器已切到 kai，本页内嵌的
 * agent 下拉仍停在 Neurova、列表仍是 Neurova 的渠道。根因：本页 agentId 是
 * 纯本地 `ref('default')`——不接路由（/channels 无 agentId 参数）、不订阅
 * store，全局切换器（AgentSwitcher autoNavigate 默认 false）只写
 * `agentStore.currentAgentId`，本页永远收不到。
 *
 * 修复契约：本页不占路由，页内下拉（v-model + onAgentChange）就是身份写入口；
 * store 的用户切换经**同一入口**落地——写回 agentId 并走 onAgentChange() 重取。
 * 守卫边界：store 的**自动兜底选中**（loadAgents 对空 currentAgentId 的默认
 * 选中，prev=null）不是用户切换，不得据此改写视图——页面落地视图仍是 default。
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
import { listChannelConfigs, getIngressStats, listPluginChannelSchemas, checkChannelConflicts } from '@/api/modules/channel-configs'
import { getNegativeScreenConfig, getPushStatistics } from '@/api/modules/negative-screen'
import { useAgentStore } from '@/stores/agents'
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
      noConfigsForAgent: '{agent} 名下暂无配置', migrateSuccess: '', migrateEmpty: '',
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

const agentSelectStub = {
  props: ['options', 'value'],
  emits: ['update:value', 'change'],
  template: `<select class="agent-select" :value="value"
    @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
    <option v-for="opt in (options || [])" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</option>
  </select>`,
}

let wrapper: VueWrapper | null = null

function mountPage(): VueWrapper {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  wrapper = mount(ChannelIntegrationPage, {
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
  return wrapper
}

function currentSelectValue(): string {
  return ((wrapper?.find('select.agent-select').element as HTMLSelectElement) ?? { value: '' }).value
}

function listCalls(): number {
  return (listChannelConfigs as unknown as { mock: { calls: unknown[][] } }).mock.calls.length
}

describe('ChannelIntegrationPage — 全局 agent 切换联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    wrapper = null
    vi.clearAllMocks()
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: AGENTS })
        return Promise.resolve({ data: [] })
      })
    ;(listChannelConfigs as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue([])
    ;(getIngressStats as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({ enabled: false })
    ;(listPluginChannelSchemas as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({ data: { schemas: [] } })
    ;(checkChannelConflicts as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({ conflicts: [] })
    ;(getNegativeScreenConfig as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({ enabled: false })
    ;(getPushStatistics as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({ code: 0, data: {} })
  })
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ''
  })

  it('store 自动兜底选中（prev=null）不改落地视图——仍停在 default', async () => {
    mountPage()
    await flushPromises()

    expect(currentSelectValue()).toBe('default')
    expect(listChannelConfigs).toHaveBeenCalledTimes(1)
  })

  it('全局切换器换 agent → 页内下拉跟随，列表按新 agent 重取', async () => {
    mountPage()
    await flushPromises()
    expect(listChannelConfigs).toHaveBeenCalledWith('default')

    const store = useAgentStore()
    store.setCurrentAgent('kai')
    await flushPromises()

    expect(currentSelectValue()).toBe('kai')
    expect(listChannelConfigs).toHaveBeenCalledWith('kai')
  })

  it('页内已选中的 agent 与全局切换同值 → 不重复取数', async () => {
    const w = mountPage()
    await flushPromises()
    // 页内路径：手动选 kai（走 onAgentChange 同一条重取路径）
    await w.find('select.agent-select').setValue('kai')
    await flushPromises()
    expect(listChannelConfigs).toHaveBeenLastCalledWith('kai')
    const callsAfterManual = listCalls()

    const store = useAgentStore()
    store.setCurrentAgent('kai')
    await flushPromises()

    expect(listCalls()).toBe(callsAfterManual)
  })
})
