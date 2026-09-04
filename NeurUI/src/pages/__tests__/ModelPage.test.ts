import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// ─── API mocks（信封形状与后端一致：{code:0, data:{...}}）───
vi.mock('@/api/modules/providers', () => ({
  listProviders: vi.fn().mockResolvedValue({ data: [] }),
  getActiveModel: vi.fn().mockResolvedValue({ data: {} }),
  activateModel: vi.fn().mockResolvedValue({ data: null }),
  updateProvider: vi.fn().mockResolvedValue({ data: null }),
  createProvider: vi.fn().mockResolvedValue({ data: null }),
  deleteProvider: vi.fn().mockResolvedValue({ data: null }),
  discoverModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
  filterProviderModels: vi.fn().mockResolvedValue({ data: { items: [] } }),
  getProviderSeries: vi.fn().mockResolvedValue({ data: [] }),
  testConnection: vi.fn(),
}))
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue({ data: [] }),
  updateModel: vi.fn().mockResolvedValue({ data: null }),
  deleteModel: vi.fn().mockResolvedValue({ data: null }),
  detectCapabilities: vi.fn().mockResolvedValue({ data: { detected: 0, results: [] } }),
}))
vi.mock('@/api/modules/settings', () => ({
  getSettings: vi.fn().mockResolvedValue({ data: {} }),
  updateSettings: vi.fn().mockResolvedValue({ data: {} }),
}))
vi.mock('@/api', () => ({
  request: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

import ModelPage from '../ModelPage.vue'
import { testConnection } from '@/api/modules/providers'
import { message } from 'ant-design-vue'

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存', success: '成功', error: '失败', close: '关闭', confirm: '确认', add: '添加', delete: '删除', edit: '编辑' },
  model: {
    title: '模型管理', providers: '服务商', models: '模型', settings: '设置', testConnection: '测试连接',
    connectionOk: '连接成功 {ms}', connectionFailed: '连接失败',
    modelManagement: '模型管理', discover: '发现模型', detectCaps: '检测能力', detectCapsTip: '检测',
    baseUrl: 'Base URL', apiKey: 'API Key', authMethod: '鉴权方式', genParams: '生成参数', genParamsDesc: 'JSON',
    advanced: '高级', headers: '请求头', addModel: '添加模型',
  },
  nav: {}, ui: {},
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div><slot name="header"/><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading', 'title'], emits: ['click'], template: '<button :title="title" @click="$emit(\'click\')"><slot/></button>' },
  'a-input': { props: ['value', 'placeholder'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-select': { props: ['value'], template: '<select><slot/></select>' },
  'a-select-option': { template: '<option><slot/></option>' },
  'a-switch': { props: ['checked'], template: '<button class="ant-switch" />' },
  'a-slider': { template: '<input type="range" />' },
  'a-input-number': { template: '<input />' },
  'a-input-password': { template: '<input type="password" />' },
  'a-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-badge': { template: '<span><slot/></span>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div><label>{{ label }}</label><slot/></div>' },
  'a-textarea': { template: '<textarea />' },
  'a-popconfirm': { template: '<span><slot/></span>' },
  'a-tooltip': { template: '<span><slot/></span>' },
  'a-collapse': { template: '<div><slot/></div>' },
  'a-collapse-panel': { template: '<div><slot/></div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(ModelPage, { global: { plugins: [i18n], stubs: globalStubs }, attachTo: document.body })
}

// 配置弹窗经 Teleport 挂在 body 上，wrapper.findAll 摸不到，须查 document
function bodyButtons(): HTMLButtonElement[] {
  return [...document.body.querySelectorAll('button')] as HTMLButtonElement[]
}

function findBtn(text: string): HTMLButtonElement | undefined {
  return bodyButtons().find((b) => (b.textContent || '').trim() === text)
}

/** 在指定 provider 卡片（.nr-pv-card，含 provider 名文本）内找设置按钮 */
function findSettingsBtnForProvider(providerName: string): HTMLButtonElement | undefined {
  const cards = [...document.querySelectorAll('.nr-pv-card')]
  const card = cards.find((c) => (c.textContent || '').includes(providerName))
  const btns = [...(card?.querySelectorAll('button') ?? [])] as HTMLButtonElement[]
  return btns.find((b) => (b.textContent || '').trim() === '设置')
}

describe('ModelPage — 测试连接信封解包（回归 2026-09-05）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(testConnection as ReturnType<typeof vi.fn>).mockReset()
  })

  afterEach(() => {
    // attachTo 挂载后须清 body，防跨测试 DOM 污染（Teleport 弹窗/卡片残留）
    document.body.innerHTML = ''
  })

  it('shows success when backend returns envelope {code:0,data:{success:true}}', async () => {
    // 后端真实形状：POST /providers/{id}/check-connection → {code:0, data:{connected:true,...}}
    ;(testConnection as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { connected: true, success: true, latency_ms: 1900, message: '' },
    })
    const wrapper = mountPage()
    await flushPromises()

    const settingsBtn = findSettingsBtnForProvider('OpenRouter')
    expect(settingsBtn, 'openrouter 内置卡应有设置按钮').toBeTruthy()
    settingsBtn!.click()
    await flushPromises()

    // 配置弹窗 Teleport 到 body
    const testBtn = bodyButtons().find((b) => (b.textContent || '').includes('测试连接'))
    expect(testBtn, '配置弹窗应有测试连接按钮').toBeTruthy()
    testBtn!.click()
    await flushPromises()

    expect(testConnection).toHaveBeenCalledWith('openrouter')
    // 信封解包修复前：data.success 为 undefined → 恒走失败分支
    expect(message.success).toHaveBeenCalled()
    expect(message.warning).not.toHaveBeenCalled()
  })

  it('still warns when backend reports real failure', async () => {
    ;(testConnection as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { connected: false, success: false, error: 'invalid api key' },
    })
    const wrapper = mountPage()
    await flushPromises()

    findSettingsBtnForProvider('OpenRouter')!.click()
    await flushPromises()
    bodyButtons().find((b) => (b.textContent || '').includes('测试连接'))!.click()
    await flushPromises()

    expect(message.warning).toHaveBeenCalled()
    expect(message.success).not.toHaveBeenCalled()
  })
})
