import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 系统渠道页·管理面动作必须带 agent 身份（Issue #290 未闭环项③ 的前端半边）。
 *
 * 后端三端点（restart / clear-queue / conflicts）已按 agent 收口，但前端调用点
 * 若不传身份，后端只能按 default 处置 —— 链条对用户端仍是断的：
 * 用户在「凯蒂」视图里点「重启」，动的是 default 的同平台实例。
 */

vi.mock('@/api', () => ({
  api: { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }), useRouter: () => ({ push: vi.fn() }) }))

// vi.mock 的工厂被提升到文件顶部，故替身必须经 vi.hoisted 声明（否则 TDZ）
const spies = vi.hoisted(() => ({
  restartChannelAdapter: vi.fn(),
  clearChannelQueue: vi.fn(),
  checkChannelConflicts: vi.fn(),
}))

vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([
    { channel_type: 'feishu', enabled: true, connected: true, extra: {} },
  ]),
  createChannelConfig: vi.fn().mockResolvedValue({}),
  testChannelConfig: vi.fn().mockResolvedValue({ success: true }),
  getIngressStats: vi.fn().mockResolvedValue({ enabled: false }),
  restartChannelAdapter: spies.restartChannelAdapter,
  clearChannelQueue: spies.clearChannelQueue,
  checkChannelConflicts: spies.checkChannelConflicts,
  listPluginChannelSchemas: vi.fn().mockResolvedValue({ data: { schemas: [] } }),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
  updateNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  testNegativeScreenPush: vi.fn().mockResolvedValue({ success: true }),
  deleteNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  getPushStatistics: vi.fn().mockResolvedValue({ code: 0, data: {} }),
}))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({
    agentOptions: [{ label: '凯蒂', value: '216fb777' }],
    loadAgents: vi.fn(),
    loadWorkflowAgents: vi.fn(),
  }),
}))

import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'

const messages = {
  'zh-CN': {
    common: { disabled: '禁用', delete: '删除', enable: '启用', yes: '是', no: '否', success: '成功', error: '错误' },
    channel: {
      title: '渠道', desc: '', defaultAgent: '默认智能体', configure: '配置', connected: '已连接',
      enabled: '已启用', noChannels: '暂无', searchPlaceholder: '搜', tabAll: '全部', tabBuiltin: '内置',
      tabCustom: '自定义', ingressQueue: '队列', ingressPending: '待处理', ingressProcessing: '处理中',
      ingressDead: '死信', ingressProcessed: '已完成', restart: '重启', restartOk: '重启成功',
      restartFail: '重启失败', clearQueue: '清空', queueCleared: '已清空', conflictCheck: '冲突检测',
      noConflicts: '无冲突', conflictFound: '发现冲突', scanAuth: '扫码授权', getQrcode: '获取二维码',
      scanHint: '提示', scanAuthSuccess: '成功', scanExpired: '过期', scanFailed: '失败',
      testConnection: '测试连接', testSuccess: '成功', testFailed: '失败', configSaveFailed: '保存失败',
      removeChannelConfirm: '删除 {name}？', enabledSection: '已激活', disabledSection: '未激活',
      botPrefixLabel: '机器人前缀', notSet: '未设置', wecomMode: '模式', wecomModeAibot: '机器人',
      wecomModeEnterprise: '企业', enable: '启用', disable: '禁用',
    },
    settings: { negativeScreen: '负一屏推送' },
    nav: {
      showToolMessages: '工具', showThinking: '思考', streamMode: '流式', privateChatStrategy: '私',
      groupChatStrategy: '群', requireMention: '@', region: '区域', feishuChina: '飞书', larkInternational: 'Lark',
      groupShareSession: '共享', tokenFile: 'Token', messageMerge: '合并', dingtalkAppKey: 'k', dingtalkAppSecret: 's',
      mediaDirectory: '媒体', replyAtSender: '@', instantConfirm: '即时', disableDm: '', disableGroup: '', receiveBotMessages: '',
    },
    ui: { chXiaoyi: '小艺', chDingtalk: '钉钉', chFeishu: '飞书', chWechat: '微信', chWecom: '企业微信', chYuanbao: '元宝' },
    negativeScreen: { testPushSuccess: 'ok', testPushFailed: 'fail', testPushTaskName: 't', testPushContent: 'c', testPushResult: 'r' },
  },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(ChannelIntegrationPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': {
          props: ['options', 'value'], emits: ['update:value', 'change'],
          template: `<select class="agent-select" :value="value"
            @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
            <option v-for="o in (options||[])" :key="String(o.value)" :value="String(o.value)">{{ o.label }}</option>
          </select>`,
        },
        'a-spin': { template: '<div><slot/></div>' }, 'a-tag': { template: '<span><slot/></span>' },
        'a-empty': { template: '<div/>' }, 'a-modal': { template: '<div><slot/></div>' },
        'a-form': { template: '<form><slot/></form>' }, 'a-form-item': { template: '<div><slot/></div>' },
        'a-switch': { template: '<button/>' }, 'a-input': { template: '<input/>' },
        'a-input-number': { template: '<input/>' }, 'a-tabs': { template: '<div><slot/></div>' },
        'a-tab-pane': { template: '<div><slot/></div>' }, 'a-input-search': { template: '<input/>' },
        'a-badge': { template: '<span><slot/></span>' }, 'a-tooltip': { template: '<span><slot/></span>' },
        NegativeScreenSettings: { template: '<div/>' }, QrcodeAuthBlock: { template: '<div/>' },
      },
    },
  })
}

describe('ChannelIntegrationPage — 管理面动作带 agent 身份', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    spies.restartChannelAdapter.mockResolvedValue({ code: 0, data: { success: true } })
    spies.clearChannelQueue.mockResolvedValue({ code: 0, data: { cleared: 0 } })
    spies.checkChannelConflicts.mockResolvedValue({ code: 0, data: { conflicts: [], checked: 0 } })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('重启渠道时把当前 agent 身份发给后端', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.agent-select').setValue('216fb777')
    await flushPromises()

    const btn = wrapper.findAll('button').find((b) => b.text().includes('重启') || b.text().includes('restart'))
    if (!btn) throw new Error('未找到重启按钮：' + wrapper.findAll('button').map((b) => b.text()).join('|'))
    await btn.trigger('click')
    await flushPromises()

    expect(spies.restartChannelAdapter).toHaveBeenCalled()
    expect(spies.restartChannelAdapter.mock.calls.at(-1)?.[1]).toBe('216fb777')
  })

  it('清空队列时把当前 agent 身份发给后端', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.agent-select').setValue('216fb777')
    await flushPromises()

    // 清空队列在配置弹窗的 footer 里（Teleport 到 body），故先经未激活 chip 打开弹窗
    const chip = wrapper.findAll('.nr-ci-chip')[0]
    if (!chip) throw new Error('未找到渠道 chip')
    await chip.trigger('click')
    await flushPromises()

    const btn = Array.from(document.body.querySelectorAll('button'))
      .find((b) => (b.textContent || '').includes('清空'))
    if (!btn) {
      throw new Error('未找到清空按钮：'
        + Array.from(document.body.querySelectorAll('button')).map((b) => b.textContent).join('|'))
    }
    btn.click()
    await flushPromises()

    expect(spies.clearChannelQueue).toHaveBeenCalled()
    expect(spies.clearChannelQueue.mock.calls.at(-1)?.[1]).toBe('216fb777')
  })
})
