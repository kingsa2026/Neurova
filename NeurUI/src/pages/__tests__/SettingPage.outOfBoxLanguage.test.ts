/**
 * SettingPage 的「开箱默认语言」一格（台账 §6-167，用户裁「先取长补短再退役」）。
 *
 * 这页原先在 general 表单里放一个语言下拉，保存即 `PUT /settings` 的 `general` 段——
 * 而那个键在**后端没有任何读者**（四份「默认语言」定义里的第一份，见台账）。
 * 现在它改指语言层，判据要抓住的是四件事，而不是"控件在不在"：
 * 1. 读数真的落到控件上，且经 `uiCodeForLanguageTag` 映射回本 UI 有语言包的那些码；
 * 2. `configured=false` 时**留空**——把"没人定过起点"显示成"起点是 zh-CN"，
 *    下一个管理员会以为已经有人做过这个决定；
 * 3. 写的是语言面，不是 settings 面：`saveSection('general')` 的提交体里不许再有 `language`
 *    （留着就是只写不读的断链重生长出来）；
 * 4. 写失败要看得见：这一格影响的是所有还没选过语言的人。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/settings', () => ({
  getSettings: vi.fn().mockResolvedValue({ settings: {} }),
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
  useAppStore: () => ({ isDark: true, toggleTheme: vi.fn(), setLocale: vi.fn(), locale: 'zh-CN' }),
}))
vi.mock('@/i18n', () => ({
  supportedLocales: [
    { code: 'zh-CN', flag: '🇨🇳', name: '简体中文' },
    { code: 'en-US', flag: '🇺🇸', name: 'English' },
  ],
  uiCodeForLanguageTag: (tag: string | null) => (tag === 'zh' ? 'zh-CN' : null),
}))
vi.mock('@/api/modules/language', () => ({
  LANGUAGE_SOURCE: { user: 'user', outOfBox: 'out_of_box', builtin: 'builtin' },
  getOutOfBoxLanguageDefault: vi.fn(),
  setOutOfBoxLanguageDefault: vi.fn(),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

import SettingPage from '../SettingPage.vue'
import { updateSettings } from '@/api/modules/settings'
import { getOutOfBoxLanguageDefault, setOutOfBoxLanguageDefault } from '@/api/modules/language'
import { message } from 'ant-design-vue'

const messages = {
  system: { settings: '系统设置' },
  common: {
    globalSettingHint: '全局设置', adminOnlyHint: '仅管理员', required: '必填',
    save: '保存', success: '成功', error: '失败',
  },
  settings: {
    general: '常规', generalSettings: '常规设置', appName: '应用名',
    outOfBoxLanguage: '开箱默认语言', outOfBoxLanguageHint: '只作用于还没自己选过语言的用户',
  },
  theme: { appearance: '外观', dark: '深色', light: '浅色' },
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div><h3>{{ title }}</h3><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button><slot/></button>' },
  'a-tabs': { template: '<div class="ant-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane"><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': {
    props: ['label', 'extra'],
    template: '<div class="ant-form-item" :data-label="label"><slot/></div>',
  },
  'a-input': { template: '<input />' },
  'a-select': { template: '<select><slot/></select>' },
  'a-select-option': { template: '<option><slot/></option>' },
  'a-switch': { template: '<button class="ant-switch" />' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  setActivePinia(createPinia())
  return mount(SettingPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

const defaultView = (over: Record<string, unknown> = {}) => ({
  data: {
    user_id: '__defaults__', configured: true, source: 'out_of_box',
    primary_language: 'zh', secondary_languages: [], fallback_language: 'en',
    auto_detect: false, updated_at: 1, ...over,
  },
})

describe('SettingPage — 开箱默认语言改指语言面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(getOutOfBoxLanguageDefault).mockResolvedValue(defaultView() as any)
  })

  it('挂载即拉一次开箱默认，并把后端码映射成本 UI 的码', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(getOutOfBoxLanguageDefault).toHaveBeenCalled()
    expect((wrapper.vm as any).outOfBoxLanguage).toBe('zh-CN')
  })

  it('没人定过起点时留空，而不是把兜底值显示成"已经定过"', async () => {
    vi.mocked(getOutOfBoxLanguageDefault).mockResolvedValue(
      defaultView({ configured: false, source: 'builtin' }) as any)

    const wrapper = mountPage()
    await flushPromises()

    expect((wrapper.vm as any).outOfBoxLanguage).toBe('')
  })

  it('本 UI 没有语言包的那个码不硬塞进下拉', async () => {
    // `uiCodeForLanguageTag` 在本夹具里只认 zh → 其它返回 null；显示成 `pt` 这种
    // 下拉里根本不存在的值，管理员保存时会拿到一个界面没给过他的码。
    vi.mocked(getOutOfBoxLanguageDefault).mockResolvedValue(
      defaultView({ primary_language: 'pt' }) as any)

    const wrapper = mountPage()
    await flushPromises()

    expect((wrapper.vm as any).outOfBoxLanguage).toBe('')
  })

  it('渲染出这一格与它的提示文案', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const labels = wrapper.findAll('.ant-form-item').map((el) => el.attributes('data-label'))
    expect(labels).toContain('开箱默认语言')
    expect(wrapper.text()).toContain('只作用于还没自己选过语言的用户')
  })

  it('保存这一格写的是语言面，不顺手 PUT settings 的 general 段', async () => {
    vi.mocked(setOutOfBoxLanguageDefault).mockResolvedValue(defaultView() as any)
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.outOfBoxLanguage = 'en-US'

    await vm.saveLanguageDefault()

    expect(setOutOfBoxLanguageDefault).toHaveBeenCalledWith(
      { primary_language: 'en-US', auto_detect: false })
    expect(updateSettings).not.toHaveBeenCalled()
    expect(message.success).toHaveBeenCalled()
  })

  it('general 段的提交体里不再有 language——那是一根只写不读的断链', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any

    await vm.saveSection('general')

    const payload = (updateSettings as ReturnType<typeof vi.fn>).mock.calls
      .find(([section]) => section === 'general')?.[1]
    expect(payload).toBeDefined()
    expect('language' in payload).toBe(false)
    // 「general 又带上 language」＝那根只写不读的断链重新长出来（§6-167 退役的正面对账）
    expect(vm.general.app_name).toBe('Neurova')
  })

  it('没选值就保存要拒并且不发包', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.outOfBoxLanguage = ''

    await vm.saveLanguageDefault()

    expect(setOutOfBoxLanguageDefault).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalled()
  })

  it('后端拒收时把失败交给用户看——这一格影响的是所有还没选过语言的人', async () => {
    vi.mocked(setOutOfBoxLanguageDefault).mockRejectedValue(new Error('400'))
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.outOfBoxLanguage = 'zh-CN'

    await vm.saveLanguageDefault()

    expect(message.error).toHaveBeenCalled()
    expect(message.success).not.toHaveBeenCalled()
  })
})
