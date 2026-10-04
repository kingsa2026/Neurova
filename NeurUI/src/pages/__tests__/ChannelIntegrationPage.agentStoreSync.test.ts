import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 系统渠道页（消息渠道，/channels）·身份契约：**只显示当前 agent，不提供切换**。
 *
 * 演进（2026-10-04 用户裁决）：本页曾有页内 agent 下拉（本地 ref + onAgentChange
 * 重取），先修过"不随全局切换刷新"，随后用户裁决**取消页内切换**——身份单源绑定
 * `agentStore.currentAgentId`（'default' 兜底），页面只显示当前 agent 名称，
 * 全局切换器换人时列表跟随重取。
 *
 * 钉四件事：
 * 1. 页面不再渲染 agent 下拉（切换面整体退役，含"查看默认智能体"按钮）；
 * 2. 显示当前 agent 的**名字**（store 里找得到时用 name，不是裸 id）；
 * 3. 全局切换 → 列表按新 agent 重取（经 onAgentChange 同一条路径）；
 * 4. store 未决时落地 default 视图（显示"默认智能体"并按 default 取数）。
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
      viewDefaultAgent: '查看默认智能体', migrateLegacyChannels: '迁移存量配置',
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

function mountPage(): VueWrapper {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(ChannelIntegrationPage, {
    global: {
      plugins: [i18n],
      stubs: {
        // a-select 假体带 data-stub 标记：页面弹层关闭时唯一的 a-select 就是
        // agent 选择器，"不再渲染切换下拉"= 该标记计数为 0（表单下拉都在弹层里）。
        'a-select': { props: ['value', 'options'], template: '<select data-stub="a-select"/>' },
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

describe('ChannelIntegrationPage — 只显示当前 agent（无切换）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
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
  afterEach(() => { document.body.innerHTML = '' })

  it('页面不再渲染 agent 切换下拉，也没有 switch-to-default 按钮', () => {
    const w = mountPage()
    expect(w.findAll('[data-stub="a-select"]').length).toBe(0)
    expect(w.find('[data-testid="switch-to-default"]').exists()).toBe(false)
  })

  it('冷挂载：loadAgents 自动兜底选中后，页面跟随显示该 agent 并按其取数', async () => {
    mountPage()
    await flushPromises()

    // store 自动兜底选中第一个 agent（agents.ts 既有行为），身份单源绑定后页面跟随。
    // listChannelConfigs 在 loadConfigs 的 schema await 边界之后才发——兜底此时已
    // 落定，故首枪即带选中身份（无 'default' 空转枪）；若兜底竞态晚于取数，
    // watch 会补一枪同身份重取，两次读数一致。
    expect(listChannelConfigs).toHaveBeenLastCalledWith('216fb777')
  })

  it('agents 为空（store 保持未决）→ 落地 default 视图：显示"默认智能体"', async () => {
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: [] })
        return Promise.resolve({ data: [] })
      })
    const w = mountPage()
    await flushPromises()

    expect(w.find('[data-testid="current-agent-name"]').text()).toBe('默认智能体')
    expect(listChannelConfigs).toHaveBeenCalledWith('default')
    expect(listChannelConfigs).toHaveBeenCalledTimes(1)
  })

  it('显示当前 agent 的名字（store 里找 name，不是裸 id）', async () => {
    const w = mountPage()
    const store = useAgentStore()
    store.setCurrentAgent('kai')
    await flushPromises()

    expect(w.find('[data-testid="current-agent-name"]').text()).toBe('凯')
  })

  it('全局切换器换 agent → 名称跟随，列表按新 agent 重取', async () => {
    const w = mountPage()
    await flushPromises()

    const store = useAgentStore()
    store.setCurrentAgent('kai')
    await flushPromises()

    expect(w.find('[data-testid="current-agent-name"]').text()).toBe('凯')
    expect(listChannelConfigs).toHaveBeenCalledWith('kai')
  })
})
