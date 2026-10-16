/**
 * SettingPage — 「Agent 运行限制」卡必须盖住配置单源全量键，且合法域取自回包。
 *
 * 病根：§6-269 把 PUT 白名单补齐到 10 键之后，面板仍只画两个输入框，其余八键
 * 「能经 API 调、不能经 UI 调」；而那两个框的 `:min="1000" :max="10000000"` 是把
 * 后端夹紧常量抄进了模板——改了常量界面区间静默不动，管理员照着一个不被服务端认的
 * 区间填数，比报错更坏的是他以为那能存（同档判据第③条防的就是这个，只不过第二份
 * 数字写在 .vue 里而不是模型里）。
 *
 * 契约（本档逐格判）：
 * 1. 控件集合 = 回包 `domains` 的键集合 ⇒ 面板能调什么由单源决定，不由这里手写清单决定；
 * 2. 每控件的 min/max 等于回包读数（改读数→控件跟着动，这条才是「没抄数字」的证据）；
 * 3. 布尔键画开关、数值键画数字框，形态也从回包取；
 * 4. 保存载荷盖住全量键（漏一键＝那一键的修改被自己的表单抹掉）；
 * 5. 回包里有前端没配文案的新键时**仍要出现一个旋钮**，标签回退成键名本身——
 *    少一句翻译不该变成少一个旋钮；
 * 6. 未加载成功时不显示任何编造的默认值与区间（F-12 同一根因：表单里是前端默认值，
 *    提交会把线上配置覆盖掉）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const getAgentLimits = vi.fn()
const updateAgentLimits = vi.fn().mockResolvedValue({})

vi.mock('@/api/modules/settings', () => ({
  getSettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateSettings: vi.fn().mockResolvedValue({}),
  clearCache: vi.fn().mockResolvedValue({}),
  getGovernanceSettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateGovernanceSettings: vi.fn().mockResolvedValue({}),
  getAgentLimits: (...a: unknown[]) => getAgentLimits(...a),
  updateAgentLimits: (...a: unknown[]) => updateAgentLimits(...a),
  getToolOffloadSettings: vi.fn().mockRejectedValue(new Error('skip')),
  updateToolOffloadSettings: vi.fn().mockResolvedValue({}),
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
vi.mock('@/i18n', () => ({
  supportedLocales: [{ code: 'zh-CN', flag: '🇨🇳', name: '简体中文' }],
  uiCodeForLanguageTag: (tag: string | null) => (tag === 'zh' ? 'zh-CN' : null),
}))
vi.mock('@/api/modules/language', () => ({
  LANGUAGE_SOURCE: { user: 'user', outOfBox: 'out_of_box', builtin: 'builtin' },
  getOutOfBoxLanguageDefault: vi.fn().mockRejectedValue(new Error('skip')),
  setOutOfBoxLanguageDefault: vi.fn().mockResolvedValue({ data: null }),
}))
vi.mock('ant-design-vue', () => ({ message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import SettingPage from '../SettingPage.vue'

/** 语言包文案：本档只用两处按文案断言（跟随提示与未知键的标签回退），其余按 data-key 定位。 */
const LABELS: Record<string, string> = {
  agentTokenBudget: 'Token 预算上限',
  agentMaxRounds: '最大 Loop 轮次',
  agentGoalMaxContinuations: '目标续跑上限',
  agentGoalRoundBudget: '目标轮次预算',
  agentGoalVerification: '目标验收开关',
  agentMaxSubagentDepth: '子代理嵌套深度',
  agentMaxParallelTools: '单批并行上限',
  agentDoomLoopWindow: '死循环窗口',
  agentDoomLoopInterrupts: '死循环中断上限',
  agentDoomLoopSimilarity: '签名相似度阈值',
}

const messages = {
  system: { settings: '系统设置' },
  common: {
    globalSettingHint: '全局设置', adminOnlyHint: '仅管理员', required: '必填',
    save: '保存', success: '成功', error: '失败', delete: '删除', close: '关闭',
  },
  settings: {
    general: '常规', generalSettings: '常规设置', appName: '应用名', llm: '模型', llmSettings: '模型设置',
    security: '安全', securitySettings: '安全设置', jwtSecret: 'JWT', jwtExpiry: '过期',
    minPasswordLength: '长度', requireSpecial: '特殊', storage: '存储', storageSettings: '存储设置',
    mediaStoragePath: '路径', maxUploadSize: '上限', cacheTtl: 'TTL', refreshCache: '清缓存',
    advanced: '高级', advancedSettings: '高级设置', debugMode: '调试', logLevel: '级别',
    debug: 'd', info: 'i', warning: 'w', error: 'e', enableTelemetry: '遥测',
    maxOutputTokens: '输出', maxOutputTokensHint: 'h', desktopRuntimeMode: '运行', desktopRuntimeModeHint: 'h',
    runtimeFull: '完全', runtimeSandbox: '沙箱', runtimeReview: '审核', runtimeAuto: '自动',
    skillRecallTitle: '召回', skillRecallHint: 'h', skillCatalogEnabled: '目录', skillCatalogEnabledHint: 'h',
    skillSchemaBudget: '预算', skillSchemaBudgetHint: 'h', evolutionQueue: '队列', evolutionQueueHint: 'h',
    skillSemanticRecall: '语义', skillSemanticRecallHint: 'h', toolSearchEnabled: '工具', toolSearchEnabledHint: 'h',
    sshHostsTitle: 'SSH', sshHostsHint: 'h', sshHostsEmpty: '无', sshHost: 'h', sshUser: 'h', sshPort: 'h',
    sshAuthType: 'h', sshAuthPassword: 'h', sshAuthKey: 'h', sshAuthAgent: 'h', sshPrivateKey: 'h', sshPassword: 'h',
    sshAddHost: 'h', sshHostRequired: 'h', sshCredentialRequired: 'h',
    socialCredentialsTitle: '社', socialCredentialsHint: 'h', socialPlatform: 'h', socialSave: 'h',
    socialConfigured: 'h', socialNotConfigured: 'h', socialClear: 'h', socialPlatformRequired: 'h',
    socialCredentialRequired: 'h', socialAlreadySet: 'h',
    negativeScreen: '负一屏', governanceTitle: '治理', governanceHint: 'h', governanceRsiPhase: 'RSI',
    governancePhase0: '0', governancePhase1: '1', governancePhase2: '2', governancePhase3: '3',
    governancePhase4: '4', governanceConversationRules: '规则',
    toolOffloadTitle: '溢出', toolOffloadHint: 'h', toolOffloadThreshold: '阈值', toolOffloadThresholdHint: 'h',
    notLoadedSaveBlocked: '尚未加载成功，已阻止保存',
    agentLimitsTitle: 'Agent 运行限制',
    agentLimitsHint: '对话循环的安全阈值',
    agentLimitsNotLoaded: '限制读数尚未加载成功',
    agentLimitFollows: '不填时跟随 {source}',
    ...LABELS,
    ...Object.fromEntries(Object.keys(LABELS).map((k) => [`${k}Hint`, `${LABELS[k]}的说明`])),
  },
  model: { providers: 'p', active: 'a' },
  agent: { temperature: 't', maxTokens: 'm' },
  theme: { language: 'l', appearance: 'a', dark: 'd', light: 'l' },
  computer: { click: '点击' },
  computerPanel: { title: '面板', empty: '空', clickHint: 'h', actionsTitle: '动作' },
}

// stub 要把 min/max 暴露成属性——"区间到底从哪来"只能从渲染结果判，读源码字符串判不出。
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
  'a-input-number': {
    props: ['value', 'min', 'max', 'step'],
    template: '<input class="num" :data-min="min" :data-max="max" :data-value="value" />',
  },
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

const ALL_KEYS = [
  'token_budget', 'max_loop_rounds', 'goal_max_continuations', 'goal_round_budget',
  'goal_verification_enabled', 'max_subagent_depth', 'max_parallel_tools',
  'doom_loop_window_size', 'doom_loop_max_interrupts', 'doom_loop_similarity_threshold',
]

/** 与后端 `get_limit_domains()` 同形的回包读数（数值故意取得与夹紧常量不同，见各格说明）。 */
function domainsOf(keys: string[], over: Record<string, unknown> = {}) {
  const out: Record<string, unknown> = {}
  for (const key of keys) {
    out[key] = key === 'goal_verification_enabled'
      ? { kind: 'bool' }
      : key === 'doom_loop_similarity_threshold'
        ? { kind: 'float', min: 0.25, max: 0.75 }
        : key === 'goal_round_budget'
          ? { kind: 'int', min: 3, max: 44, follows: 'max_loop_rounds' }
          : { kind: 'int', min: 3, max: 44 }
  }
  return { ...out, ...over }
}

function valuesOf(keys: string[]) {
  const out: Record<string, unknown> = {}
  for (const key of keys) out[key] = key === 'goal_verification_enabled' ? true : 7
  return out
}

function limitsResponse(keys: string[] = ALL_KEYS, over: Record<string, unknown> = {}) {
  return { data: { data: valuesOf(keys), domains: domainsOf(keys, over) } }
}

/** 找到某个配置键那一行（按 `data-key` 定位——把断言与文案措辞解耦）。 */
function itemOf(wrapper: ReturnType<typeof mountPage>, key: string) {
  const rows = wrapper.findAll(`.limit-row[data-key="${key}"]`)
  expect(rows.length, `键 ${key} 应恰有一行控件`).toBe(1)
  return rows[0]
}

describe('SettingPage — Agent 运行限制卡盖住配置单源全量键', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    updateAgentLimits.mockResolvedValue({})
  })

  it('回包给几键就画几个控件：全量十键都在面板上', async () => {
    getAgentLimits.mockResolvedValue(limitsResponse())
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.findAll('.limit-row').length, '控件行数应等于回包键数').toBe(ALL_KEYS.length)
    for (const key of ALL_KEYS) {
      expect(itemOf(wrapper, key).find('.num, .sw').exists(), `${key} 应有控件`).toBe(true)
    }
  })

  it('区间取自回包读数：改掉读数，控件的 min/max 必须跟着动', async () => {
    // 这一格才是"数字没抄进模板"的证据：按源码字符串比对判不出——抄的那份此刻恰好相等。
    getAgentLimits.mockResolvedValue(limitsResponse())
    const wrapper = mountPage()
    await flushPromises()
    const num = itemOf(wrapper, 'token_budget').find('.num')
    expect(num.attributes('data-min'), '应为回包里的 3，不是模板里抄的 1000').toBe('3')
    expect(num.attributes('data-max'), '应为回包里的 44，不是模板里抄的 10000000').toBe('44')
  })

  it('控件形态取自读数：布尔键画开关，数值键画数字框', async () => {
    getAgentLimits.mockResolvedValue(limitsResponse())
    const wrapper = mountPage()
    await flushPromises()
    expect(itemOf(wrapper, 'goal_verification_enabled').find('.sw').exists()).toBe(true)
    expect(itemOf(wrapper, 'goal_verification_enabled').find('.num').exists()).toBe(false)
    expect(itemOf(wrapper, 'max_parallel_tools').find('.num').exists()).toBe(true)
  })

  it('数值控件回填的是生效值，不是前端编的数', async () => {
    getAgentLimits.mockResolvedValue(limitsResponse())
    const wrapper = mountPage()
    await flushPromises()
    expect(itemOf(wrapper, 'doom_loop_window_size').find('.num').attributes('data-value')).toBe('7')
  })

  it('保存载荷盖住全量键：漏一键＝那一键的修改被自己的表单抹掉', async () => {
    getAgentLimits.mockResolvedValue(limitsResponse())
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).saveAgentLimits()
    const sent = updateAgentLimits.mock.calls[0][0] as Record<string, unknown>
    expect(Object.keys(sent).sort()).toEqual([...ALL_KEYS].sort())
  })

  it('回包里有前端没配文案的新键时仍出现旋钮，标签回退成键名', async () => {
    // 少一句翻译不该变成少一个旋钮——这一格防的是"面板按前端手写键名白名单渲染"那种写法。
    getAgentLimits.mockResolvedValue(limitsResponse([...ALL_KEYS, 'brand_new_knob']))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.findAll('.limit-row').length).toBe(ALL_KEYS.length + 1)
    const row = itemOf(wrapper, 'brand_new_knob')
    expect(row.find('.num, .sw').exists()).toBe(true)
    expect(row.find('.fi').attributes('data-label'), '没有文案时至少要让人看见这个旋钮叫什么')
      .toBe('brand_new_knob')
  })

  it('跟随哨兵的语义要上屏：goal_round_budget 得让管理员知道不填时取谁', async () => {
    getAgentLimits.mockResolvedValue(limitsResponse())
    const wrapper = mountPage()
    await flushPromises()
    expect(itemOf(wrapper, 'goal_round_budget').text()).toContain('不填时跟随 max_loop_rounds')
  })

  it('未加载成功时不编造默认值与区间（F-12 同根因）', async () => {
    getAgentLimits.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    const card = wrapper.findAll('.gc').find((n) => n.text().includes('Agent 运行限制'))
    expect(card, '卡片应仍在').toBeTruthy()
    expect(card!.findAll('.num').length, '没有读数就不该有带着编造值的数字框').toBe(0)
    expect(card!.text()).toContain('限制读数尚未加载成功')
    await (wrapper.vm as any).saveAgentLimits()
    expect(updateAgentLimits).not.toHaveBeenCalled()
  })
})
