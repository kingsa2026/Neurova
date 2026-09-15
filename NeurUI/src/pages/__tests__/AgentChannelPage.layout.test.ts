import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Agent 渠道页·双面板布局。
 * 钉：已激活进大卡面板、未激活进紧凑小卡面板、负一屏出现在未激活面板。
 */

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { agentId: 'default' } }) }))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({ agentOptions: [], loadAgents: vi.fn() }),
}))
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([
    { channel_type: 'telegram', enabled: true, connected: true, extra: { bot_prefix: '@nv' } },
  ]),
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

import AgentChannelPage from '../AgentChannelPage.vue'

const messages = {
  'zh-CN': {
    common: { disabled: '禁用', delete: '删除', enable: '启用', yes: '是', no: '否', success: '成功', error: '错误' },
    channel: {
      agentChannels: '渠道配置', agentChannelsDesc: '', defaultAgent: '默认', configure: '配置',
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

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(AgentChannelPage, {
    global: {
      plugins: [i18n],
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

describe('AgentChannelPage 双面板布局', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => { document.body.innerHTML = '' })

  it('已启用渠道进大卡面板，其余进未激活紧凑面板，负一屏在未激活面板', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const enabled = wrapper.find('[data-testid="panel-enabled"]')
    const disabled = wrapper.find('[data-testid="panel-disabled"]')
    expect(enabled.exists()).toBe(true)
    expect(disabled.exists()).toBe(true)

    // telegram 已启用 → 大卡面板，且显示机器人前缀 @nv
    expect(enabled.text()).toContain('Telegram')
    expect(enabled.text()).toContain('@nv')
    // 未配置的飞书在紧凑面板；负一屏也在紧凑面板（NV 独有）
    const chips = disabled.findAll('.nr-ac-chip').map((c) => c.text())
    expect(chips.some((t) => t.includes('飞书'))).toBe(true)
    expect(chips.some((t) => t.includes('负一屏推送'))).toBe(true)
    // 已启用面板不应出现未激活的飞书
    expect(enabled.text()).not.toContain('飞书')
  })
})
