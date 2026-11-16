import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'

/**
 * fe-P2-4（用户拍板 2026-11-16）：Agent 渠道页启用/禁用点击即落库。
 * 原形态只翻本地 enabled（注释自述"真正落盘在保存时"）；现契约：
 * POST /channel-configs（全量 upsert，已存凭据原样回传防抹空）→ 成功才翻 UI。
 */
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { agentId: 'default' } }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({ agentOptions: [], loadAgents: vi.fn(), loadWorkflowAgents: vi.fn(), currentAgentId: 'default', agents: [] }),
}))
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn(),
  createChannelConfig: vi.fn(),
  deleteChannelConfig: vi.fn(),
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
import AgentChannelPage from '../AgentChannelPage.vue'
import { listChannelConfigs, createChannelConfig } from '@/api/modules/channel-configs'
import { message } from 'ant-design-vue'

const listMock = listChannelConfigs as unknown as ReturnType<typeof vi.fn>
const createMock = createChannelConfig as unknown as ReturnType<typeof vi.fn>

const messages = {
  'zh-CN': {
    common: { delete: '删除', enable: '启用', success: '成功', error: '错误', yes: '是', no: '否', cancel: '取消', save: '保存', confirm: '确认' },
    channel: {
      agentChannels: '渠道配置', agentChannelsDesc: '', defaultAgent: '默认', configure: '配置',
      connected: '已连接', enabled: '已启用', enabledNotConnected: '已启用未连接', noChannels: '暂无', enable: '启用', disable: '禁用',
      configSaveFailed: '保存失败', removeChannelConfirm: '删除 {name}？',
      scanAuth: '扫码授权', getQrcode: '获取二维码', scanHint: '提示',
      scanAuthSuccess: '成功', scanExpired: '过期', scanFailed: '失败',
      enabledSection: '已激活', disabledSection: '未激活', botPrefixLabel: '机器人前缀', notSet: '未设置',
      wecomMode: '模式', wecomModeAibot: '机器人', wecomModeEnterprise: '企业',
    },
    settings: { negativeScreen: '负一屏推送' },
    nav: {
      showToolMessages: '工具', showThinking: '思考', streamMode: '流式', privateChatStrategy: '私',
      groupChatStrategy: '群', requireMention: "{'@'}", region: '区域', feishuChina: '飞书', larkInternational: 'Lark',
      groupShareSession: '共享', tokenFile: 'Token', messageMerge: '合并', dingtalkAppKey: 'k', dingtalkAppSecret: 's',
      mediaDirectory: '媒体', replyAtSender: "{'@'}", instantConfirm: '即时', disableDm: '', disableGroup: '', receiveBotMessages: '',
    },
    ui: { chTelegram: 'Telegram', chFeishu: '飞书', chDingtalk: '钉钉' },
  },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, messages })
  return mount(AgentChannelPage, {
    global: {
      plugins: [i18n, createPinia()],
      stubs: {
        'a-select': { template: '<div><slot/></div>' },
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



beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  // message 是真实 ant-design-vue 出口：用 spy 断言（不 mock 模块，页面其余导出保真）
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never)
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never)
  listMock.mockResolvedValue([
    { channel_type: 'telegram', enabled: true, connected: false, extra: { app_id: 'tg-1', bot_prefix: '@nv' } },
  ] as never)
  createMock.mockResolvedValue({ code: 0, data: { success: true } } as never)
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('AgentChannelPage — 渠道启用/禁用点击即落库（fe-P2-4）', () => {
  it('已启用渠道点「禁用」：POST 落库成功后才翻 UI，且回传已存凭据', async () => {
    const wrapper = mountPage()
    await flushPromises()

    // 目录里 Console 卡默认 enabled（backendType='api'），必须按卡名点 telegram 那张
    const tgCard = wrapper.findAll('.nr-ac-card').find((c) => (c.text() || '').includes('Telegram'))
    expect(tgCard, 'telegram 应在已激活面板').toBeTruthy()
    const disableBtn = tgCard!.findAll('button').find((b) => (b.text() || '').trim() === '禁用')
    expect(disableBtn).toBeTruthy()
    await disableBtn!.trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    const [payload, agentIdParam] = createMock.mock.calls[0] as [Record<string, unknown>, string]
    expect(payload).toMatchObject({ channel_type: 'telegram', enabled: false, app_id: 'tg-1' })
    expect((payload.extra as Record<string, unknown>)).toMatchObject({ app_id: 'tg-1', bot_prefix: '@nv' })
    expect(agentIdParam).toBe('default')
    expect(message.success).toHaveBeenCalled()
    // 成功后从已激活大卡面板移入未激活紧凑面板（Console 卡目录默认 enabled，面板仍会存在）
    const enabledCards = wrapper.findAll('.nr-ac-card').map((c) => c.text() || '')
    expect(enabledCards.some((txt) => txt.includes('Telegram'))).toBe(false)
    expect(wrapper.findAll('.nr-ac-chip').some((c) => (c.text() || '').includes('Telegram'))).toBe(true)
  })

  it('落库失败不翻 UI 并透出 detail 原话', async () => {
    createMock.mockRejectedValue({ response: { status: 409, data: { detail: '平台身份冲突' } } })

    const wrapper = mountPage()
    await flushPromises()

    const tgCard = wrapper.findAll('.nr-ac-card').find((c) => (c.text() || '').includes('Telegram'))
    const disableBtn = tgCard!.findAll('button').find((b) => (b.text() || '').trim() === '禁用')
    await disableBtn!.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="panel-enabled"]').exists()).toBe(true)
    expect(message.error).toHaveBeenCalledWith('平台身份冲突')
  })

  it('未配置渠道点「启用」：直接 POST 创建配置（enabled:true）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const chip = wrapper.findAll('.nr-ac-chip').find((c) => (c.text() || '').includes('飞书'))
    expect(chip, '未激活面板应有飞书 chip').toBeTruthy()
    const enableBtn = chip!.findAll('button').find((b) => (b.text() || '').trim() === '启用')
    expect(enableBtn).toBeTruthy()
    await enableBtn!.trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    const [payload, agentIdParam] = createMock.mock.calls[0] as [Record<string, unknown>, string]
    expect(payload).toMatchObject({ channel_type: 'feishu', enabled: true, app_id: '', app_secret: '' })
    expect(agentIdParam).toBe('default')
  })
})
