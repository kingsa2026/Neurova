import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

/**
 * fe-P2-4（用户拍板 2026-11-16）：渠道启用/禁用按钮改**点击即落库**。
 *
 * 原形态：toggleChannel 只翻本地 `ch.enabled`，注释自述"真正落盘在保存时"——
 * UI 状态与后端不一致（刷新即打脸），且"未配置先启用"根本进不了后端。
 * 现契约：点击 → POST /channel-configs（回传已存 extra 防凭据被抹空）→
 * 成功才翻 UI；失败保持后端现状并 toast。
 */
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn(),
  createChannelConfig: vi.fn(),
  testChannelConfig: vi.fn(),
  getIngressStats: vi.fn().mockResolvedValue({ enabled: false }),
  restartChannelAdapter: vi.fn().mockResolvedValue({}),
  clearChannelQueue: vi.fn(),
  checkChannelConflicts: vi.fn(),
  listPluginChannelSchemas: vi.fn().mockResolvedValue({ data: { schemas: [] } }),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
  updateNegativeScreenConfig: vi.fn().mockResolvedValue({ data: { enabled: true } }),
  testNegativeScreenPush: vi.fn().mockResolvedValue({ success: true }),
  deleteNegativeScreenConfig: vi.fn(),
  getPushStatistics: vi.fn().mockResolvedValue({ code: 0, data: {} }),
}))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({ currentAgentId: 'default', agents: [], agentOptions: [] }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'
import { listChannelConfigs, createChannelConfig } from '@/api/modules/channel-configs'

const listMock = listChannelConfigs as unknown as ReturnType<typeof vi.fn>
const createMock = createChannelConfig as unknown as ReturnType<typeof vi.fn>

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存', refresh: '刷新' },
  channel: {
    integration: '渠道集成', integrationDesc: '管理消息渠道', all: '全部', builtin: '内置',
    customChannel: '自定义渠道', noChannels: '暂无渠道', connected: '已连接', enabled: '已启用',
    disabled: '未启用', enable: '启用', disable: '禁用', configure: '配置', configureDesc: '配置渠道参数',
    test: '测试', testSuccess: '测试通过', testFailed: '测试失败', configSaved: '配置已保存',
    configSaveFailed: '保存失败', commonSettings: '通用设置', platformSettings: '平台设置',
    ingressQueue: '入站队列', ingressPending: '待处理', ingressProcessing: '处理中',
    ingressDead: '死信', ingressProcessed: '已处理', enabledSection: '已启用渠道',
    disabledSection: '未启用渠道', restart: '重启', clearQueue: '清空队列', notSet: '未设置',
    botPrefixLabel: '前缀', defaultAgent: '默认智能体', accessDenied: '无权访问',
    genericFailure: '失败: {reason}',
  },
  settings: { negativeScreen: '负一屏推送' },
  negativeScreen: { title: '负一屏推送设置' },
  ui: { chDingtalk: '钉钉', chFeishu: '飞书' },
  ui2: {},
}

const globalStubs = {
  GlassCard: { template: '<div><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\', $event)"><slot/></button>' },
  GlassInput: { props: ['modelValue', 'placeholder'], template: '<input />' },
  NegativeScreenSettings: { template: '<div />' },
  ChannelMigrationDialog: { template: '<div />' },
  QrcodeAuthBlock: { template: '<div />' },
  Teleport: { template: '<div><slot/></div>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-switch': { template: '<button class="ant-switch" />' },
  'a-input': { template: '<input />' },
  'a-input-password': { template: '<input type="password" />' },
  'a-select': { template: '<select/>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<label><slot/></label>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, messages: { 'zh-CN': messages } })
  return mount(ChannelIntegrationPage, { global: { plugins: [i18n], stubs: globalStubs }, attachTo: document.body })
}

function chipEnableBtn(name: string): HTMLButtonElement | undefined {
  const chips = [...document.querySelectorAll('.nr-ci-chip')]
  const chip = chips.find((c) => (c.textContent || '').includes(name))
  return [...(chip?.querySelectorAll('button') ?? [])].find(
    (b) => (b.textContent || '').trim() === '启用',
  ) as HTMLButtonElement | undefined
}

beforeEach(() => {
  vi.clearAllMocks()
  listMock.mockResolvedValue([
    { channel_type: 'feishu', enabled: true, connected: false, extra: { app_id: 'ak-1', app_secret: 'sk-1', use_stream: true } },
  ] as never)
  createMock.mockResolvedValue({ code: 0, data: { success: true } } as never)
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ChannelIntegrationPage — 渠道启用/禁用点击即落库（fe-P2-4）', () => {
  it('已启用渠道点「禁用」：POST 落库成功后才翻 UI，且回传已存凭据', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const enabledPanel = wrapper.find('[data-testid="panel-enabled"]')
    expect(enabledPanel.exists()).toBe(true)
    const disableBtn = enabledPanel.findAll('button').find((b) => (b.text() || '').trim() === '禁用')
    expect(disableBtn, '已启用渠道卡应有「禁用」按钮').toBeTruthy()

    await disableBtn!.trigger('click')
    await flushPromises()

    // 落库：channel_type + enabled:false + 已存凭据原样回传（防 POST 全量替换抹空凭据）
    expect(createMock).toHaveBeenCalledTimes(1)
    const [payload, agentIdParam] = createMock.mock.calls[0] as [Record<string, unknown>, string]
    expect(payload).toMatchObject({
      channel_type: 'feishu',
      enabled: false,
      app_id: 'ak-1',
      app_secret: 'sk-1',
      use_stream: true,
    })
    expect((payload.extra as Record<string, unknown>)).toMatchObject({ app_id: 'ak-1', app_secret: 'sk-1' })
    expect(agentIdParam).toBe('default')

    // UI 与后端一致：成功后渠道移入未启用面板
    expect(wrapper.find('[data-testid="panel-enabled"]').exists()).toBe(false)
    expect(chipEnableBtn('飞书')).toBeTruthy()
  })

  it('落库失败不翻 UI：渠道留在已启用面板（状态与后端一致）', async () => {
    createMock.mockRejectedValue({ response: { status: 409, data: { detail: '平台身份冲突' } } })

    const wrapper = mountPage()
    await flushPromises()

    const disableBtn = wrapper.find('[data-testid="panel-enabled"]').findAll('button')
      .find((b) => (b.text() || '').trim() === '禁用')
    await disableBtn!.trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="panel-enabled"]').exists()).toBe(true)
  })

  it('未配置渠道点「启用」：直接 POST 创建配置（enabled:true）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const enableBtn = chipEnableBtn('钉钉')
    expect(enableBtn, '未启用渠道 chip 应有「启用」按钮').toBeTruthy()
    await enableBtn!.click()
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    const [payload, agentIdParam] = createMock.mock.calls[0] as [Record<string, unknown>, string]
    expect(payload).toMatchObject({ channel_type: 'dingtalk', enabled: true, app_id: '', app_secret: '' })
    expect(agentIdParam).toBe('default')
    // 落库成功后从 chip 面板消失（移入已启用面板）
    expect(chipEnableBtn('钉钉')).toBeUndefined()
  })
})
