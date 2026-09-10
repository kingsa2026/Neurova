/**
 * SettingPage 保存守卫回归测试（F-12）。
 *
 * 缺陷：fetchAgentLimits / fetchGovernance 失败时静默吞错（表单停留前端
 * 默认值），用户点保存会把默认值回写覆盖线上配置。
 * 修复契约：
 * - 加载成功 → loaded 标志置位，保存正常提交；
 * - 加载失败 → loaded 保持 false，保存前置校验拦截：message.warning + 不提交；
 * - 加载失败本身 console.error + 不阻断页面（非阻断不变）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/settings', () => ({
  getSettings: vi.fn().mockResolvedValue({ data: {} }),
  updateSettings: vi.fn().mockResolvedValue({ data: {} }),
  clearCache: vi.fn().mockResolvedValue({ data: {} }),
  getGovernanceSettings: vi.fn(),
  updateGovernanceSettings: vi.fn().mockResolvedValue({ data: {} }),
  getAgentLimits: vi.fn(),
  updateAgentLimits: vi.fn().mockResolvedValue({ data: {} }),
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
import {
  getAgentLimits,
  getGovernanceSettings,
  updateAgentLimits,
  updateGovernanceSettings,
} from '@/api/modules/settings'
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

// antd 组件轻 stub（沿用 SettingPage.test.ts 的stub集合）
const globalStubs = {
  GlassCard: { props: ['title'], template: '<div><h3>{{ title }}</h3><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button><slot/></button>' },
  'a-tabs': { template: '<div class="ant-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { template: '<div class="ant-form-item"><slot/></div>' },
  'a-input': { template: '<input />' },
  'a-select': { template: '<select><slot/></select>' },
  'a-select-option': { template: '<option><slot/></option>' },
  'a-switch': { template: '<button class="ant-switch" />' },
  'a-slider': { template: '<input type="range" />' },
  'a-input-number': { template: '<input class="ant-input-number" />' },
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

describe('SettingPage — 未加载禁止保存（F-12 回归）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getAgentLimits as ReturnType<typeof vi.fn>).mockReset()
    ;(getGovernanceSettings as ReturnType<typeof vi.fn>).mockReset()
  })

  it('Agent 限制加载成功 → 保存正常提交', async () => {
    ;(getAgentLimits as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { data: { token_budget: 555, max_loop_rounds: 7 } },
    })
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).saveAgentLimits()
    expect(updateAgentLimits).toHaveBeenCalledWith(expect.objectContaining({ token_budget: 555, max_loop_rounds: 7 }))
    expect(message.success).toHaveBeenCalled()
    expect(message.warning).not.toHaveBeenCalled()
  })

  it('Agent 限制加载失败 → 保存被拦截并警告（防默认值回写覆盖线上配置）', async () => {
    ;(getAgentLimits as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).saveAgentLimits()
    expect(updateAgentLimits).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalled()
    // 加载失败本身仍要有错误日志（禁止表面抹除）
    expect(consoleSpy).toHaveBeenCalled()
    consoleSpy.mockRestore()
  })

  it('治理配置加载成功 → 保存正常提交', async () => {
    ;(getGovernanceSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { data: { rsi_phase: 2, conversation_rules_enabled: true } },
    })
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).saveGovernance()
    expect(updateGovernanceSettings).toHaveBeenCalledWith(expect.objectContaining({ rsi_phase: 2 }))
    expect(message.success).toHaveBeenCalled()
    expect(message.warning).not.toHaveBeenCalled()
  })

  it('治理配置加载失败 → 保存被拦截并警告', async () => {
    ;(getGovernanceSettings as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).saveGovernance()
    expect(updateGovernanceSettings).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalled()
    consoleSpy.mockRestore()
  })
})
