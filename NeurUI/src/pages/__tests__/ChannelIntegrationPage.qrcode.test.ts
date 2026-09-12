import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 渠道配置页·通用扫码授权闭环（QwenPaw 两段式对齐，2026-09-13）。
 * 钉：QR 渠道弹窗出现扫码块 → 点获取二维码出图 → 轮询 success 后凭据自动
 * 回填表单；非 QR 渠道不出现扫码块（诚实接线，不搞摆设按钮）。
 */

vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([]),
  createChannelConfig: vi.fn().mockResolvedValue({}),
  testChannelConfig: vi.fn().mockResolvedValue({ success: true }),
  getIngressStats: vi.fn().mockResolvedValue({ enabled: false }),
  restartChannelAdapter: vi.fn().mockResolvedValue({}),
  clearChannelQueue: vi.fn().mockResolvedValue({}),
  checkChannelConflicts: vi.fn().mockResolvedValue({ data: { conflicts: [] } }),
  listPluginChannelSchemas: vi.fn().mockResolvedValue({ data: { schemas: [] } }),
  createWechatIlinkQrcode: vi.fn().mockResolvedValue({ status: 'ready' }),
  getChannelQrcode: vi.fn().mockResolvedValue({ qrcode_img: 'ZmFrZS1wbmc=', poll_token: 'pt-1' }),
  getChannelQrcodeStatus: vi.fn().mockResolvedValue({
    status: 'success',
    credentials: { app_id: 'cli_a', app_secret: 'sec_b' },
  }),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
  updateNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  testNegativeScreenPush: vi.fn().mockResolvedValue({ success: true }),
  deleteNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  getPushStatistics: vi.fn().mockResolvedValue({ code: 0, data: {} }),
}))

import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'
import { getChannelQrcode, getChannelQrcodeStatus } from '@/api/modules/channel-configs'

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存' },
  channel: {
    integration: '渠道集成', integrationDesc: '管理消息渠道', all: '全部', builtin: '内置',
    customChannel: '自定义渠道', noChannels: '暂无渠道', connected: '已连接', enabled: '已启用',
    disabled: '未启用', enable: '启用', disable: '禁用', configure: '配置',
    configureDesc: '配置渠道参数', test: '测试', testSuccess: '测试通过', testFailed: '测试失败',
    configSaved: '配置已保存', configSaveFailed: '保存失败', commonSettings: '通用设置',
    platformSettings: '平台设置', ingressQueue: '入站队列', ingressPending: '待处理',
    ingressProcessing: '处理中', ingressDead: '死信', ingressProcessed: '已处理',
    scanAuth: '扫码授权', getQrcode: '获取二维码', scanHint: '扫码后自动回填',
    scanAuthSuccess: '扫码授权成功', scanExpired: '二维码过期', scanFailed: '扫码失败',
    qrcodeFetching: '生成中', enabledSection: '已激活', disabledSection: '未激活',
    botPrefixLabel: '机器人前缀', notSet: '未设置',
  },
  settings: { negativeScreen: '负一屏推送' },
  ui: { chXiaoyi: '小艺', chFeishu: '飞书', chDingtalk: '钉钉', chWechat: '微信', chWecom: '企业微信' },
  nav: {
    showToolMessages: '工具', showThinking: '思考', streamMode: '流式', privateChatStrategy: '私聊',
    groupChatStrategy: '群聊', requireMention: '@', region: '区域', feishuChina: '飞书',
    larkInternational: 'Lark', groupShareSession: '共享会话', tokenFile: 'Token 文件',
    messageMerge: '合并', dingtalkAppKey: 'key', dingtalkAppSecret: 'sec',
  },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(ChannelIntegrationPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassInput: { props: ['modelValue', 'placeholder'], template: '<input />' },
        'a-select': { template: '<div><slot/></div>' },
        'a-spin': { template: '<div><slot/></div>' },
        'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
      },
    },
  })
}

async function openModalFor(wrapper: any, name: string) {
  // 未激活渠道在紧凑面板：点 chip 打开配置弹窗
  const chip = wrapper.findAll('.nr-ci-chip').find((c: any) => c.text().includes(name))
  expect(chip, `${name} 应出现在未激活面板`).toBeTruthy()
  await chip!.trigger('click')
  await flushPromises()
  return document.body.querySelector('.nr-ci-modal')!
}

describe('渠道页·扫码授权闭环', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  })
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('飞书弹窗出现扫码块，取码出图，轮询成功后凭据回填 App ID/App Secret 并提示', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const modal = await openModalFor(wrapper, '飞书')
    const qrBlock = modal.querySelector('[data-testid="qrcode-auth-block"]')
    expect(qrBlock, '飞书支持扫码授权').toBeTruthy()

    ;(qrBlock!.querySelector('[data-testid="qrcode-fetch-btn"]') as HTMLElement).click()
    await flushPromises()
    expect(getChannelQrcode).toHaveBeenCalledWith('feishu', expect.anything())
    expect(qrBlock!.querySelector('[data-testid="qrcode-img"]'), '应展示 base64 PNG 二维码').toBeTruthy()

    // 推进一次轮询（feishu pollInterval=2000）
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(getChannelQrcodeStatus).toHaveBeenCalledWith('feishu', 'pt-1', expect.anything())

    const inputs = modal.querySelectorAll('.nr-ci-section input')
    const values = Array.from(inputs).map((i: any) => i.value)
    expect(values, 'app_id/app_secret 应被回填').toContain('cli_a')
    expect(values).toContain('sec_b')
    const toast = document.body.querySelector('.nr-ci-toast')
    expect(toast?.textContent).toContain('扫码授权成功')
  })

  it('Telegram 无扫码 handler，弹窗不得出现扫码块（不摆假按钮）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const modal = await openModalFor(wrapper, 'Telegram')
    expect(modal.querySelector('[data-testid="qrcode-auth-block"]'), 'Telegram 不支持扫码').toBeNull()
  })
})
