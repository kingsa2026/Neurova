/**
 * SettingPage — 高级选项卡「技能召回与进化」卡
 *
 * 验收：
 * - 卡渲染三开关 + 各自功能说明
 * - fetchSettings 回填 advanced 段的三个布尔键（默认全开=后端 ADVANCED_DEFAULTS 对齐）
 * - saveSkillRecall 仅写 advanced 段三键（后端 merge，不触碰同段其它设置）
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
    skillRecallTitle: '技能召回与进化', skillRecallHint: '三开关说明总述',
    skillCatalogEnabled: '技能目录常驻', skillCatalogEnabledHint: '目录提示说明',
    skillSchemaBudget: '技能Schema预算', skillSchemaBudgetHint: '预算提示说明',
    evolutionQueue: '进化作业队列', evolutionQueueHint: '队列提示说明',
    skillSemanticRecall: '语义检索档', skillSemanticRecallHint: '语义提示说明',
    toolSearchEnabled: '工具延迟加载', toolSearchEnabledHint: '工具搜索提示说明',
    sshHostsTitle: 'SSH', sshHostsHint: 'h', sshHostsEmpty: '无', sshHost: 'h', sshUser: 'h', sshPort: 'h',
    sshAuthType: 'h', sshAuthPassword: 'h', sshAuthKey: 'h', sshAuthAgent: 'h', sshPrivateKey: 'h', sshPassword: 'h',
    sshAddHost: 'h', sshHostRequired: 'h', sshCredentialRequired: 'h',
    socialCredentialsTitle: '社', socialCredentialsHint: 'h', socialPlatform: 'h', socialSave: 'h',
    socialConfigured: 'h', socialNotConfigured: 'h', socialClear: 'h', socialPlatformRequired: 'h',
    socialCredentialRequired: 'h', socialAlreadySet: 'h',
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
  'a-switch': { props: ['checked'], emits: ['update:checked'], template: '<button class="sw" />' },
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

describe('SettingPage — 技能召回与进化卡', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    updateSettings.mockResolvedValue({})
    getSettings.mockResolvedValue({
      settings: {
        advanced: {
          skill_catalog_enabled: true,
          skill_schema_budget_enabled: false,
          evolution_queue_enabled: true,
        },
      },
    })
  })

  it('渲染卡片：标题+总述+五个开关说明', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('技能召回与进化')
    expect(text).toContain('目录提示说明')
    expect(text).toContain('预算提示说明')
    expect(text).toContain('队列提示说明')
    expect(text).toContain('语义提示说明')
    expect(text).toContain('工具搜索提示说明')
  })

  it('fetchSettings 回填三个开关值', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.advanced.skill_catalog_enabled).toBe(true)
    expect(vm.advanced.skill_schema_budget_enabled).toBe(false)
    expect(vm.advanced.evolution_queue_enabled).toBe(true)
  })

  it('前端默认值与后端默认全开对齐', () => {
    const wrapper = mountPage()
    const vm = wrapper.vm as any
    expect(vm.advanced.skill_catalog_enabled).toBe(true)
    expect(vm.advanced.skill_schema_budget_enabled).toBe(true)
    expect(vm.advanced.evolution_queue_enabled).toBe(true)
  })

  it('saveSkillRecall 仅写 advanced 段五键', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.advanced.skill_schema_budget_enabled = true
    vm.advanced.tool_search_enabled = false
    await vm.saveSkillRecall()
    expect(updateSettings).toHaveBeenCalledWith('advanced', {
      skill_catalog_enabled: true,
      skill_schema_budget_enabled: true,
      evolution_queue_enabled: true,
      skill_semantic_recall_enabled: true,
      tool_search_enabled: false,
    })
  })
})
