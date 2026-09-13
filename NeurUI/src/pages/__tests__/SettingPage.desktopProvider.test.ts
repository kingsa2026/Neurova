/**
 * SettingPage — 安全选项卡「桌面沙箱提供方」卡
 *
 * 验收：
 * - 安全选项卡渲染提供方卡（标题+提示+下拉）
 * - fetchSettings 回填 advanced.desktop_provider
 * - saveDesktopProvider 仅写 advanced 段 {desktop_provider}（后端 merge 持久化）
 * - 选项含 未配置/sandbox/rdp（与 runtime_policy 无池 fail-closed 语义对齐）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const getSettings = vi.fn()
const updateSettings = vi.fn().mockResolvedValue({})

vi.mock('@/api/modules/settings', () => ({
  getSettings: (...a: unknown[]) => getSettings(...a),
  updateSettings: (...a: unknown[]) => updateSettings(...a),
  clearCache: vi.fn().mockResolvedValue({}),
  getGovernanceSettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateGovernanceSettings: vi.fn().mockResolvedValue({}),
  getAgentLimits: vi.fn().mockRejectedValue(new Error('skip')),
  updateAgentLimits: vi.fn().mockResolvedValue({}),
  getLlmRetrySettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateLlmRetrySettings: vi.fn().mockResolvedValue({}),
  listSSHCredentials: vi.fn().mockResolvedValue({ data: { hosts: [] } }),
  upsertSSHCredential: vi.fn().mockResolvedValue({}),
  deleteSSHCredential: vi.fn().mockResolvedValue({}),
  listSocialCredentials: vi.fn().mockResolvedValue({ data: { platforms: [] } }),
  setSocialCredential: vi.fn().mockResolvedValue({}),
  clearSocialCredential: vi.fn().mockResolvedValue({}),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }) }))
vi.mock('@/stores/app', () => ({ useAppStore: () => ({ isDark: true, toggleTheme: vi.fn(), setLocale: vi.fn() }) }))
vi.mock('@/i18n', () => ({ supportedLocales: [{ code: 'zh-CN', flag: '🇨🇳', name: '简体中文' }] }))
vi.mock('ant-design-vue', () => ({ message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import SettingPage from '../SettingPage.vue'

const messages = {
  system: { settings: '系统设置' },
  common: { globalSettingHint: '全局设置', adminOnlyHint: '仅管理员', required: '必填', save: '保存', success: '成功', error: '失败', delete: '删除', close: '关闭' },
  settings: {
    general: '常规', generalSettings: '常规设置', appName: '应用名', llm: '模型', llmSettings: '模型设置',
    security: '安全', securitySettings: '安全设置', jwtSecret: 'JWT', jwtExpiry: '过期', minPasswordLength: '长度', requireSpecial: '特殊',
    storage: '存储', storageSettings: '存储设置', mediaStoragePath: '路径', maxUploadSize: '上限', cacheTtl: 'TTL', refreshCache: '清缓存',
    advanced: '高级', advancedSettings: '高级设置', debugMode: '调试', logLevel: '级别', debug: 'd', info: 'i', warning: 'w', error: 'e', enableTelemetry: '遥测',
    maxOutputTokens: '输出', maxOutputTokensHint: 'h', desktopRuntimeMode: '运行', desktopRuntimeModeHint: 'h',
    runtimeFull: '完全', runtimeSandbox: '沙箱', runtimeReview: '审核', runtimeAuto: '自动',
    desktopProviderTitle: '桌面沙箱提供方', desktopProviderHint: '提供方提示',
    desktopProviderNone: '未配置（变更动作将被拒绝）', desktopProviderSandbox: 'Windows 沙箱', desktopProviderRdp: 'RDP 直连',
    sshHostsTitle: 'SSH 远程主机', sshHostsHint: 'h', sshHostsEmpty: '无主机', sshHost: '主机', sshUser: '用户', sshPort: '端口',
    sshAuthType: '认证', sshAuthPassword: '密码', sshAuthKey: '私钥', sshAuthAgent: '系统', sshPrivateKey: '私钥', sshPassword: '密码',
    sshAddHost: '添加主机', sshHostRequired: '请填写主机', sshCredentialRequired: '请填写凭据',
    socialCredentialsTitle: '社交平台凭据', socialCredentialsHint: 'h', socialPlatform: '平台', socialSave: '保存',
    socialConfigured: '已配置', socialNotConfigured: '未配置', socialClear: '清除', socialPlatformRequired: '请选择平台',
    socialCredentialRequired: '请填写凭据值', socialAlreadySet: '已设置',
    negativeScreen: '负一屏', governanceTitle: '治理', governanceHint: 'h', governanceRsiPhase: 'RSI',
    agentLimitsTitle: '限制', agentLimitsHint: 'h', agentTokenBudget: 'b', agentTokenBudgetHint: 'h', agentMaxRounds: 'r', agentMaxRoundsHint: 'h',
    governancePhase0: '0', governancePhase1: '1', governancePhase2: '2', governancePhase3: '3', governancePhase4: '4', governanceConversationRules: '规则',
    notLoadedSaveBlocked: 'h',
  },
  model: { providers: 'p', active: 'a' },
  agent: { temperature: 't', maxTokens: 'm' },
  theme: { language: 'l', appearance: 'a', dark: 'd', light: 'l' },
  computer: { click: '点击' },
  computerPanel: { title: '面板', empty: '空', clickHint: 'h', actionsTitle: '动作' },
}

const stubs = {
  GlassCard: { props: ['title'], template: '<div class="gc"><h3>{{ title }}</h3><slot /><slot name="footer" /></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
  UiIcon: { template: '<i />' },
  NegativeScreenSettings: { template: '<div />' },
  'a-tabs': { template: '<div><slot /></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div><slot /></div>' },
  'a-form': { template: '<form><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<div class="fi" :data-label="label"><slot /></div>' },
  'a-input': { props: ['value'], template: '<input />' },
  'a-input-password': { props: ['value'], template: '<input type="password" />' },
  'a-textarea': { props: ['value'], template: '<textarea />' },
  'a-input-number': { props: ['value'], template: '<input class="num" />' },
  'a-select': { props: ['value'], template: '<select><slot /></select>' },
  'a-select-option': { props: ['value'], template: '<option :value="value"><slot /></option>' },
  'a-switch': { template: '<button />' },
  'a-slider': { template: '<input type="range" />' },
  'a-tag': { template: '<span class="tag"><slot /></span>' },
  'a-spin': { template: '<div><slot /></div>' },
  'a-badge': { template: '<span><slot /></span>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  setActivePinia(createPinia())
  return mount(SettingPage, { global: { plugins: [i18n], stubs } })
}

describe('SettingPage — 桌面沙箱提供方卡', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    updateSettings.mockResolvedValue({})
    getSettings.mockResolvedValue({
      settings: { advanced: { desktop_provider: 'sandbox', desktop_runtime_mode: 'review' } },
    })
  })

  it('安全选项卡渲染提供方卡（标题+提示+三选项）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('桌面沙箱提供方')
    expect(wrapper.text()).toContain('提供方提示')
    const options = wrapper.findAll('option').map((o) => o.text())
    expect(options).toContain('未配置（变更动作将被拒绝）')
    expect(options).toContain('Windows 沙箱')
    expect(options).toContain('RDP 直连')
  })

  it('fetchSettings 回填 advanced.desktop_provider', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.advanced.desktop_provider).toBe('sandbox')
  })

  it('saveDesktopProvider 仅写 advanced 段 desktop_provider 键', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.advanced.desktop_provider = 'rdp'
    await vm.saveDesktopProvider()
    expect(updateSettings).toHaveBeenCalledWith('advanced', { desktop_provider: 'rdp' })
  })
})
