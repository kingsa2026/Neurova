import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

// ─── API mocks ───
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([]),
  createChannelConfig: vi.fn().mockResolvedValue({}),
  testChannelConfig: vi.fn().mockResolvedValue({ success: true }),
  getIngressStats: vi.fn().mockResolvedValue({ enabled: false }),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({
    data: { user_id: 'u1', auth_code: 'AC-123', enabled: true, push_url: 'https://push.example.com' },
  }),
  updateNegativeScreenConfig: vi.fn().mockResolvedValue({ data: { enabled: true } }),
  testNegativeScreenPush: vi.fn().mockResolvedValue({ data: { success: true, task_id: 't1' } }),
  deleteNegativeScreenConfig: vi.fn().mockResolvedValue({ data: {} }),
}))
// NegativeScreenSettings 组件用裸 request 拉配置/统计
vi.mock('@/api', () => ({
  request: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'
import { updateNegativeScreenConfig, testNegativeScreenPush, getNegativeScreenConfig } from '@/api/modules/negative-screen'
import { listChannelConfigs } from '@/api/modules/channel-configs'

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存' },
  channel: {
    integration: '渠道集成',
    integrationDesc: '管理消息渠道',
    all: '全部',
    builtin: '内置',
    customChannel: '自定义渠道',
    noChannels: '暂无渠道',
    connected: '已连接',
    enabled: '已启用',
    disabled: '已停用',
    enable: '启用',
    configure: '配置',
    configureDesc: '配置渠道参数',
    test: '测试',
    testSuccess: '测试通过',
    testFailed: '测试失败',
    configSaved: '配置已保存',
    configSaveFailed: '保存失败',
    commonSettings: '通用设置',
    platformSettings: '平台设置',
    ingressQueue: '入站队列',
    ingressPending: '待处理',
    ingressProcessing: '处理中',
    ingressDead: '死信',
    ingressProcessed: '已处理',
  },
  settings: { negativeScreen: '负一屏推送' },
  negativeScreen: {
    title: '负一屏推送设置',
    enable: '启用负一屏推送',
    enableHint: '开启后，任务完成结果将自动推送到华为负一屏',
    authCode: '授权码 (Auth Code)',
    authCodePlaceholder: '输入负一屏授权码',
    getAuthCodeSteps: '获取授权码步骤：',
    step1: '打开华为手机负一屏',
    step2: '进入 设置 → 动态管理 → 关联账号',
    step3: '找到 "Claw 智能体" 并获取授权码',
    pushUrl: '推送服务 URL',
    pushUrlPlaceholder: '推送服务地址',
    pushUrlHint: '默认使用华为官方推送服务',
    testPush: '测试推送',
    testSuccess: '✓ 推送成功',
    testFailed: '✗ ',
    deleteConfig: '删除配置',
    statsTitle: '推送统计',
    totalNotifications: '任务通知总数',
    pushedCount: '已推送数量',
    failedCount: '推送失败数量',
    successRate: '推送成功率',
    configSaved: '配置已保存',
    saveFailed: '保存配置失败',
    configDeleted: '配置已删除',
    deleteFailed: '删除配置失败',
    testPushSuccess: '测试推送成功！请查看负一屏',
    testPushFailed: '测试推送失败',
  },
  ui: {
    chXiaoyi: '小艺',
    loadNegScreenConfigFailed: '加载负一屏配置失败',
    saveNegScreenConfigFailed: '保存负一屏配置失败',
    deleteNegScreenConfigFailed: '删除负一屏配置失败',
    loadPushStatsFailed: '加载推送统计失败',
    testPushTaskName: '测试推送',
    testPushContent: '内容',
    testPushResult: '结果',
  },
  nav: { showToolMessages: '显示工具消息', showThinking: '显示思考', streamMode: '流式', privateChatStrategy: '私聊策略', groupChatStrategy: '群聊策略', requireMention: '需要@', replyAtSender: '回复@发送者', region: '区域', feishuChina: '飞书', larkInternational: 'Lark', mediaDirectory: '媒体目录', groupShareSession: '共享会话', receiveBotMessages: '接收机器人消息', instantConfirm: '即时确认', tokenFile: 'Token 文件', messageMerge: '消息合并', welcomeMessage: '欢迎语', disableDm: '禁用私聊', disableGroup: '禁用群聊' },
  ui2: {},
}

const stubs = {
  // GlassCard/GlassButton 刻意不 stub（玻璃外壳回归教训）；GlassInput 是轻输入壳，stub 掉避免 i18n 依赖噪音
  GlassInput: { props: ['modelValue', 'placeholder'], template: '<input />' },
  // NegativeScreenSettings 内嵌表单需要 label 真实渲染成文本
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div class="ant-form-item"><label>{{ label }}</label><slot/></div>' },
  'a-switch': { template: '<button class="ant-switch" />' },
  'a-input': { template: '<input />' },
  'a-input-password': { template: '<input type="password" />' },
  'a-descriptions': { template: '<div class="ant-descriptions"><slot/></div>' },
  'a-descriptions-item': { props: ['label'], template: '<div class="ant-descriptions-item"><b>{{ label }}</b><slot/></div>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(ChannelIntegrationPage, { global: { plugins: [i18n], stubs } })
}

function negCard(wrapper: ReturnType<typeof mountPage>) {
  const cards = wrapper.findAll('.nr-ci-card')
  return cards.find((c) => c.text().includes('负一屏推送'))
}

describe('ChannelIntegrationPage — 负一屏推送渠道卡', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(listChannelConfigs as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(getNegativeScreenConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { user_id: 'u1', auth_code: 'AC-123', enabled: true, push_url: 'https://push.example.com' },
    })
  })

  it('renders negative screen as a channel card with enabled state from its own API', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(getNegativeScreenConfig).toHaveBeenCalled()
    const card = negCard(wrapper)
    expect(card, '负一屏推送应作为渠道卡出现在网格中').toBeTruthy()
    // GET 返回 enabled=true → 卡片启用按钮应显示"停用"（即当前已启用）
    expect(card!.text()).toContain('停用')
  })

  it('persists enable toggle through the negative screen API instead of local-only flip', async () => {
    const wrapper = mountPage()
    await flushPromises()
    ;(updateNegativeScreenConfig as ReturnType<typeof vi.fn>).mockClear()
    ;(updateNegativeScreenConfig as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { enabled: false } })

    const card = negCard(wrapper)!
    const toggleBtn = card.findAll('button').find((b) => b.text().includes('停用'))!
    await toggleBtn.trigger('click')
    await flushPromises()

    expect(updateNegativeScreenConfig).toHaveBeenCalledWith({ enabled: false })
    // 切换成功后按钮应变为"启用"（当前已停用）
    expect(card.text()).toContain('启用')
  })

  it('opens a config modal embedding the negative screen settings when 配置 clicked', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const card = negCard(wrapper)!
    const configBtn = card.findAll('button').find((b) => b.text().includes('配置'))!
    await configBtn.trigger('click')
    await flushPromises()

    const modal = document.body.querySelector('.nr-ci-modal')
    expect(modal, '配置弹窗应挂载到 body').toBeTruthy()
    // 弹窗内嵌 NegativeScreenSettings：标题 + 授权码步骤指引齐全
    expect(modal!.textContent).toContain('负一屏推送设置')
    expect(modal!.textContent).toContain('获取授权码步骤')
    expect(modal!.textContent).toContain('推送服务 URL')
  })

  it('runs test push through the negative screen API when 测试 clicked', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const card = negCard(wrapper)!
    const testBtn = card.findAll('button').find((b) => b.text().trim() === '测试')!
    await testBtn.trigger('click')
    await flushPromises()

    expect(testNegativeScreenPush).toHaveBeenCalledTimes(1)
  })
})
