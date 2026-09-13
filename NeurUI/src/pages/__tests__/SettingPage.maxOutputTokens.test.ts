/**
 * SettingPage 高级选项卡 — 最大输出 Token 设置（max_output_tokens）回归测试。
 *
 * 病根链（修复前）：
 * 1. 后端 GET /settings 返回 {settings: {...}} 包裹壳，页面读 res?.data 恒
 *    undefined → 所有分区（含高级设置）从来没有被回填过；
 * 2. max_output_tokens 参数后端全链就绪（app_settings 持久化 + agent 热应用），
 *    但前端没有设置入口 → 思考模型吃满输出预算导致空回复时用户无从调整。
 * 修复契约：
 * - fetchSettings 用真实后端契约壳（res.settings ?? res.data）回填；
 * - advanced 分区含 max_output_tokens，默认 131072（= 跟随模型默认的哨兵值）；
 * - saveSection('advanced') 提交体携带 max_output_tokens。
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
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }),
}))
vi.mock('@/stores/app', () => ({
  useAppStore: () => ({ isDark: true, toggleTheme: vi.fn(), setLocale: vi.fn() }),
}))
vi.mock('@/i18n', () => ({
  supportedLocales: [{ code: 'zh-CN', flag: '🇨🇳', name: '简体中文' }],
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
    desktopRuntimeMode: '桌面运行权限', desktopRuntimeModeHint: '本机/沙箱/审批',
    runtimeFull: '完全放开', runtimeSandbox: '沙箱运行', runtimeReview: '审核模式', runtimeAuto: '自动模式',
    negativeScreen: '负一屏推送',
    governanceTitle: '进化治理', governanceHint: '提示', governanceRsiPhase: 'RSI 部署阶段',
    agentLimitsTitle: 'Agent 运行限制', agentLimitsHint: '提示', agentTokenBudget: 'Token 预算上限',
    agentTokenBudgetHint: '提示', agentMaxRounds: '最大 Loop 轮次', agentMaxRoundsHint: '提示',
    governancePhase0: '0', governancePhase1: '1', governancePhase2: '2', governancePhase3: '3',
    governancePhase4: '4', governanceConversationRules: '对话规则提取',
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
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  setActivePinia(createPinia())
  return mount(SettingPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

describe('SettingPage — 最大输出 Token 设置（max_output_tokens）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('fetchSettings 用真实后端包裹壳回填（res.settings，含 max_output_tokens）', async () => {
    ;(getSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      settings: {
        general: { app_name: 'Neurova', language: 'zh-CN' },
        advanced: {
          debug_mode: true,
          log_level: 'debug',
          telemetry: true,
          max_output_tokens: 16384,
        },
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.advanced.max_output_tokens).toBe(16384), '后端值必须回填（unwrap 修复）'
    expect(vm.advanced.debug_mode).toBe(true)
    expect(vm.general.app_name).toBe('Neurova')
  })

  it('advanced 默认含 max_output_tokens=131072（跟随模型默认的哨兵值）', () => {
    const wrapper = mountPage()
    expect((wrapper.vm as any).advanced.max_output_tokens).toBe(131072)
  })

  it('saveSection("advanced") 提交体携带 max_output_tokens', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.advanced.max_output_tokens = 20480
    await vm.saveSection('advanced')
    expect(updateSettings).toHaveBeenCalledWith(
      'advanced',
      expect.objectContaining({ max_output_tokens: 20480 }),
    )
    expect(message.success).toHaveBeenCalled()
  })

  it('高级卡片渲染最大输出 Token 输入与提示', () => {
    const wrapper = mountPage()
    // antd 被 stub 后 label 只落 data-label 属性（不进 text()），走属性断言
    const labels = wrapper.findAll('.ant-form-item').map((el) => el.attributes('data-label'))
    expect(labels).toContain('最大输出 Token')
    expect(wrapper.find('.ant-form-item .form-extra').text()).toContain('单次回复的输出预算上限')
    expect(wrapper.findAll('.ant-input-number').length).toBeGreaterThan(0)
  })

  it('桌面运行权限档默认 full，可保存提交', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.advanced.desktop_runtime_mode).toBe('full')
    // 渲染出运行档选择器（label 走 data-label 属性）
    const labels = wrapper.findAll('.ant-form-item').map((el) => el.attributes('data-label'))
    expect(labels).toContain('桌面运行权限')
    vm.advanced.desktop_runtime_mode = 'sandbox'
    await vm.saveSection('advanced')
    expect(updateSettings).toHaveBeenCalledWith(
      'advanced',
      expect.objectContaining({ desktop_runtime_mode: 'sandbox' }),
    )
  })
})
