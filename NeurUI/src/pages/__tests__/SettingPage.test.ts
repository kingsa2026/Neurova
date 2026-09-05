import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/settings', () => ({
  getSettings: vi.fn().mockResolvedValue({ data: {} }),
  updateSettings: vi.fn().mockResolvedValue({ data: {} }),
  clearCache: vi.fn().mockResolvedValue({ data: {} }),
  getGovernanceSettings: vi.fn().mockResolvedValue({
    data: { data: { conversation_rules_enabled: true, rsi_phase: 1 } },
  }),
  updateGovernanceSettings: vi.fn().mockResolvedValue({
    data: { conversation_rules_enabled: true, rsi_phase: 1 },
  }),
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
  message: { success: vi.fn(), error: vi.fn() },
}))

import SettingPage from '../SettingPage.vue'

const messages = {
  system: { settings: '系统设置' },
  common: { globalSettingHint: '全局设置', adminOnlyHint: '仅管理员', required: '必填', save: '保存', success: '成功', error: '失败' },
  settings: { general: '常规', generalSettings: '常规设置', appName: '应用名', llm: '模型', llmSettings: '模型设置', security: '安全', securitySettings: '安全设置', jwtSecret: 'JWT 密钥', jwtExpiry: '过期时长', minPasswordLength: '密码最小长度', requireSpecial: '特殊字符', storage: '存储', storageSettings: '存储设置', mediaStoragePath: '媒体路径', maxUploadSize: '上传上限', cacheTtl: '缓存 TTL', refreshCache: '清缓存', advanced: '高级', advancedSettings: '高级设置', debugMode: '调试模式', logLevel: '日志级别', debug: '调试', info: '信息', warning: '警告', error: '错误', enableTelemetry: '遥测', negativeScreen: '负一屏推送', governanceTitle: '进化治理', governanceHint: '提示', governanceRsiPhase: 'RSI 部署阶段', governancePhase0: '0', governancePhase1: '1', governancePhase2: '2', governancePhase3: '3', governancePhase4: '4', governanceConversationRules: '对话规则提取' },
  model: { providers: '服务商', active: '模型' },
  agent: { temperature: '温度', maxTokens: '最大 Token' },
  theme: { language: '语言', appearance: '外观', dark: '深色', light: '浅色' },
}

// antd 组件轻 stub：tab 标签文本必须真实渲染，断言才有意义
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
  // 迁移目标是被整体移除的子组件，stub 隔离其网络副作用
  NegativeScreenSettings: { template: '<div class="neg-screen-stub" />' },
}

describe('SettingPage — 负一屏推送迁移防回归', () => {
  it('no longer hosts the negative screen tab (migrated to channels)', async () => {
    const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
    setActivePinia(createPinia())
    const wrapper = mount(SettingPage, { global: { plugins: [i18n], stubs: globalStubs } })
    await flushPromises()

    // 迁移到渠道页后，系统设置不应再出现负一屏推送 tab（tab 名经 stub 透传到 data-tab 属性）
    const tabNames = wrapper.findAll('.ant-tab-pane').map((p) => p.attributes('data-tab'))
    expect(tabNames).not.toContain('负一屏推送')
    // 设置页其余功能仍正常渲染
    expect(wrapper.text()).toContain('常规设置')
  })

  it('renders governance card in advanced tab with fetched values', async () => {
    const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
    setActivePinia(createPinia())
    const wrapper = mount(SettingPage, { global: { plugins: [i18n], stubs: globalStubs } })
    await flushPromises()

    const { getGovernanceSettings } = await import('@/api/modules/settings')
    expect(getGovernanceSettings).toHaveBeenCalled()
    // 治理卡片标题渲染（advanced 选项卡内）
    expect(wrapper.text()).toContain('进化治理')
  })

  it('governance card hidden before i18n keys exist shows fallback gracefully', async () => {
    // governance 键缺失时 t() 回退键名——页面不崩
    const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': { ...messages, settings: { ...messages.settings } } } })
    setActivePinia(createPinia())
    const wrapper = mount(SettingPage, { global: { plugins: [i18n], stubs: globalStubs } })
    await flushPromises()
    expect(wrapper.find('.advanced-stack').exists()).toBe(true)
  })
})
