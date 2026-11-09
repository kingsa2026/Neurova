/**
 * SettingPage 高级选项卡 — 图谱子图上限（graph_studio_limit）回归测试。
 *
 * 病根链（用户实测）：图谱工作台截断提示写着「可在图谱页调大 limit」，
 * 但全站没有任何设置入口——studio/subgraph 的缺省上限（后端 200）与前端
 * 探索器写死的 500/200 三处并行，用户 250 节点恒被截到 200。
 * 修复契约（与后端单源配套）：
 * - advanced 分区含 graph_studio_limit，默认 200（= 后端 ADVANCED_DEFAULTS 同值）；
 * - saveSection('advanced') 提交体携带 graph_studio_limit；
 * - 高级设置卡渲染该输入与提示（区间 1–2000 与端点合法域一致）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/settings', () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn().mockResolvedValue({ data: null }),
  clearCache: vi.fn().mockResolvedValue({ data: null }),
  getGovernanceSettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateGovernanceSettings: vi.fn().mockResolvedValue({ data: null }),
  getAgentLimits: vi.fn().mockRejectedValue(new Error('skip')),
  updateAgentLimits: vi.fn().mockResolvedValue({ data: null }),
  getToolOffloadSettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateToolOffloadSettings: vi.fn().mockResolvedValue({ data: null }),
  getLlmRetrySettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateLlmRetrySettings: vi.fn().mockResolvedValue({ data: null }),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }),
}))
vi.mock('@/stores/app', () => ({
  useAppStore: () => ({ isDark: true, toggleTheme: vi.fn(), setLocale: vi.fn() }),
}))
vi.mock('@/i18n', () => ({
  supportedLocales: [{ code: 'zh-CN', flag: '🇨🇳', name: '简体中文' }],
  uiCodeForLanguageTag: (tag: string | null) => (tag === 'zh' ? 'zh-CN' : null),
}))
vi.mock('@/api/modules/language', () => ({
  LANGUAGE_SOURCE: { user: 'user', outOfBox: 'out_of_box', builtin: 'builtin' },
  getOutOfBoxLanguageDefault: vi.fn().mockRejectedValue(new Error('skip')),
  setOutOfBoxLanguageDefault: vi.fn().mockResolvedValue({ data: null }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

import SettingPage from '../SettingPage.vue'
import { getSettings, updateSettings } from '@/api/modules/settings'
import { message } from 'ant-design-vue'

const messages = {
  system: { settings: '系统设置' },
  common: { globalSettingHint: '全局设置', adminOnlyHint: '仅管理员', required: '必填', save: '保存', success: '成功', error: '失败' },
  settings: {
    general: '常规', generalSettings: '常规设置', appName: '应用名', llm: '模型', llmSettings: '模型设置',
    security: '安全', securitySettings: '安全设置', jwtSecret: 'JWT 密钥', jwtExpiry: '过期时长',
    minPasswordLength: '密码最小长度', requireSpecial: '特殊字符', storage: '存储', storageSettings: '存储设置',
    mediaStoragePath: '媒体路径', maxUploadSize: '上传上限', cacheTtl: '缓存 TTL', refreshCache: '清缓存',
    advanced: '高级', advancedSettings: '高级设置', debugMode: '调试模式', logLevel: '日志级别',
    debug: '调试', info: '信息', warning: '警告', error: '错误', enableTelemetry: '遥测',
    maxOutputTokens: '最大输出 Token', maxOutputTokensHint: '单次回复的输出预算上限',
    graphStudioLimit: '图谱子图上限', graphStudioLimitHint: '图谱工作台单次加载的最大节点数',
    desktopRuntimeMode: '桌面运行权限', desktopRuntimeModeHint: '本机/沙箱/审批',
    runtimeFull: '完全放开', runtimeSandbox: '沙箱运行', runtimeReview: '审核模式', runtimeAuto: '自动模式',
    negativeScreen: '负一屏推送',
    governanceTitle: '进化治理', governanceHint: '提示', governanceRsiPhase: 'RSI 部署阶段',
    agentLimitsTitle: 'Agent 运行限制', agentLimitsHint: '提示', agentTokenBudget: 'Token 预算上限',
    agentTokenBudgetHint: '提示', agentMaxRounds: '最大 Loop 轮次', agentMaxRoundsHint: '提示',
    governancePhase0: '0', governancePhase1: '1', governancePhase2: '2', governancePhase3: '3',
    governancePhase4: '4', governancePhase5: '5', governanceConversationRules: '对话规则提取',
    notLoadedSaveBlocked: '设置尚未加载成功，已阻止保存（避免默认值覆盖线上配置）',
  },
  model: { providers: '服务商', active: '模型' },
  agent: { temperature: '温度', maxTokens: '最大 Token' },
  theme: { language: '语言', appearance: '外观', dark: '深色', light: '浅色' },
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div><h3>{{ title }}</h3><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button><slot/></button>' },
  'a-tabs': { template: '<div class="ant-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': {
    props: ['label', 'extra'],
    template: '<div class="ant-form-item" :data-label="label"><em v-if="extra" class="form-extra">{{ extra }}</em><slot/></div>',
  },
  'a-input': { template: '<input />' },
  'a-select': { template: '<select><slot/></select>' },
  'a-select-option': { template: '<option><slot/></option>' },
  'a-switch': { template: '<button class="ant-switch" />' },
  'a-slider': { template: '<input type="range" />' },
  'a-input-number': { props: ['value'], template: '<input class="ant-input-number" />' },
  'a-input-password': { template: '<input type="password" />' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-badge': { template: '<span><slot/></span>' },
  NegativeScreenSettings: { template: '<div class="neg-screen-stub" />' },
  CredentialManager: { template: '<div class="credential-stub" />' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  setActivePinia(createPinia())
  return mount(SettingPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

describe('SettingPage — 图谱子图上限（graph_studio_limit）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('advanced 默认含 graph_studio_limit=200（与后端 ADVANCED_DEFAULTS 同值）', () => {
    const wrapper = mountPage()
    expect((wrapper.vm as any).advanced.graph_studio_limit).toBe(200)
  })

  it('fetchSettings 后端值回填 graph_studio_limit', async () => {
    ;(getSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      settings: {
        advanced: { graph_studio_limit: 800 },
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect((wrapper.vm as any).advanced.graph_studio_limit).toBe(800)
  })

  it('saveSection("advanced") 提交体携带 graph_studio_limit', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.advanced.graph_studio_limit = 1000
    await vm.saveSection('advanced')
    expect(updateSettings).toHaveBeenCalledWith(
      'advanced',
      expect.objectContaining({ graph_studio_limit: 1000 }),
    )
    expect(message.success).toHaveBeenCalled()
  })

  it('高级卡片渲染图谱子图上限输入与提示', () => {
    const wrapper = mountPage()
    const labels = wrapper.findAll('.ant-form-item').map((el) => el.attributes('data-label'))
    expect(labels).toContain('图谱子图上限')
    const extras = wrapper.findAll('.form-extra').map((el) => el.text())
    expect(extras.some((txt) => txt.includes('图谱工作台单次加载的最大节点数'))).toBe(true)
    expect(wrapper.findAll('.ant-input-number').length).toBeGreaterThan(0)
  })
})
