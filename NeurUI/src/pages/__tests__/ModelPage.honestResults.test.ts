/**
 * 回归 2026-09-14：诚实反馈三连。
 * 1. 模型连接测试结果必须渲染在该模型行正下方的容器里（非一闪 toast）。
 * 2. 发现失败提示优先展示后端 message（"请先配置 API Key"），
 *    不得被前端通用 kindHints 覆盖。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const listProviders = vi.fn()
const listModels = vi.fn()
const checkModelConnection = vi.fn()
const discoverModelsStructured = vi.fn()

vi.mock('@/api/modules/providers', () => ({
  listProviders: (...a: any[]) => listProviders(...a),
  getActiveModel: vi.fn().mockResolvedValue({ data: {} }),
  activateModel: vi.fn().mockResolvedValue({ data: null }),
  updateProvider: vi.fn().mockResolvedValue({ data: null }),
  createProvider: vi.fn().mockResolvedValue({ data: null }),
  deleteProvider: vi.fn().mockResolvedValue({ data: null }),
  discoverModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
  discoverModelsStructured: (...a: any[]) => discoverModelsStructured(...a),
  mergeDiscoveredModels: vi.fn().mockResolvedValue({ code: 0, data: { merged_count: 0 } }),
  filterProviderModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
  getProviderSeries: vi.fn().mockResolvedValue({ data: { series: [] } }),
  testConnection: vi.fn(),
}))
vi.mock('@/api/modules/models', () => ({
  listModels: (...a: any[]) => listModels(...a),
  updateModel: vi.fn().mockResolvedValue({ data: null }),
  deleteModel: vi.fn().mockResolvedValue({ data: null }),
  detectCapabilities: vi.fn().mockResolvedValue({ data: { detected: 0, results: [] } }),
  checkModelConnection: (...a: any[]) => checkModelConnection(...a),
  probeModelMultimodal: vi.fn(),
}))
vi.mock('@/api/modules/settings', () => ({
  getSettings: vi.fn().mockResolvedValue({ data: {} }),
  updateSettings: vi.fn().mockResolvedValue({ data: {} }),
}))
vi.mock('@/api', () => ({
  request: { get: vi.fn().mockResolvedValue({ data: {} }), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }),
}))
const message = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }))
vi.mock('ant-design-vue', () => ({ message }))

import ModelPage from '../ModelPage.vue'

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存', success: '成功', error: '失败', confirm: '确认' },
  model: {
    modelManagement: '模型管理', models: '模型', discover: '发现模型',
    detectCaps: '检测能力', detectCapsTip: '检测',
    noNewModels: '没有发现新模型', modelsDiscovered: '发现 {n} 个新模型',
    discoverFailed: '发现模型失败', discoverNotConfigured: '发现失败：服务商实例未就绪',
    discoverAddable: '可添加的模型', addAll: '全部添加', addFiltered: '添加',
    searchModels: '搜索', addModel: '添加模型', editModel: '编辑', delete: '删除',
    settings: '设置', testConnectionTip: '测试连接', probeMultimodalTip: '探测',
    userAdded: '手动', freeModels: '免费', builtin: '内置', save: '保存',
    connectionOk: '连接成功', connectionFailed: '连接失败',
    verifiedProviderOnly: '仅服务商连通',
    testMissingApiKey: 'API Key 未配置，请先在设置中填写',
    testInsufficientBalance: '余额或积分不足，请到服务商官网充值后重试',
    testPermissionDenied: '权限不足', testModelNotFound: '模型不存在',
    testIncompatible: 'API 不兼容', testRateLimited: '限频', testTransient: '暂不可用',
  },
  nav: {}, ui: {},
}

const globalStubs = {
  GlassCard: { props: ['title', 'variant', 'padding'], template: '<div><slot name="header"/><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading', 'title'], emits: ['click'], template: '<button :title="title" :disabled="loading" @click="$emit(\'click\')"><slot/></button>' },
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
  'a-popconfirm': { template: '<span><slot/></span>' },
  'a-tooltip': { template: '<span><slot/></span>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(ModelPage, { global: { plugins: [i18n], stubs: globalStubs }, attachTo: document.body })
}

async function openModelManagement() {
  const wrapper = mountPage()
  await flushPromises()
  const card = [...document.querySelectorAll('.nr-pv-card')].find((c) => (c.textContent || '').includes('OpenAI'))
  ;(card!.querySelector('.nr-pv-actions .nr-action-btn.primary') as HTMLButtonElement).click()
  await flushPromises()
  return wrapper
}

describe('ModelPage — 测试结果容器化显示（回归 2026-09-14）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listProviders.mockResolvedValue({
      data: [{ provider_id: 'openai', name: 'OpenAI', api_key: 'sk-test', models: [{ id: 'gpt-4o', name: 'GPT-4o' }] }],
    })
    listModels.mockResolvedValue({ data: [{ model_id: 'gpt-4o', name: 'GPT-4o', provider: 'openai' }] })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('模型连接测试失败结果渲染在模型行下方容器内，而非 toast', async () => {
    checkModelConnection.mockResolvedValue({
      code: 0,
      data: {
        connected: false, success: false,
        error_category: 'configuration', status: 'configuration',
        error_hint: '该服务商尚未配置 API Key，请先填写 API Key 后再测试模型连接',
      },
    })
    await openModelManagement()
    const item = [...document.querySelectorAll('.nr-mm-list .nr-mm-item')].find((r) => (r.textContent || '').includes('gpt-4o'))!
    const testBtn = [...(item.querySelectorAll('.nr-mm-icon-btn') as NodeListOf<HTMLButtonElement>)].find((b) => b.getAttribute('title') === '测试连接')!
    testBtn.click()
    await flushPromises()

    const result = document.querySelector('.nr-mm-item-result')
    expect(result, '模型行下方应出现结果容器').toBeTruthy()
    expect(result!.textContent).toContain('该服务商尚未配置 API Key')
    expect(result!.className).toContain('result-error')
    // 结果不再以 toast 形式一闪而过
    expect(message.error).not.toHaveBeenCalled()
    expect(message.success).not.toHaveBeenCalled()
  })

  it('余额不足状态展示后端可行动提示', async () => {
    checkModelConnection.mockResolvedValue({
      code: 0,
      data: {
        connected: false, success: false,
        error_category: 'insufficient_balance', status: 'insufficient_balance',
        error_hint: '账户余额或积分不足，请到该服务商官网充值/续费后重试',
      },
    })
    await openModelManagement()
    const item = [...document.querySelectorAll('.nr-mm-list .nr-mm-item')].find((r) => (r.textContent || '').includes('gpt-4o'))!
    const testBtn = [...(item.querySelectorAll('.nr-mm-icon-btn') as NodeListOf<HTMLButtonElement>)].find((b) => b.getAttribute('title') === '测试连接')!
    testBtn.click()
    await flushPromises()
    const result = document.querySelector('.nr-mm-item-result')
    expect(result!.textContent).toContain('余额或积分不足')
  })

  it('发现失败时优先展示后端 message（缺 API Key 提示）', async () => {
    discoverModelsStructured.mockResolvedValue({
      code: 0,
      data: {
        provider_id: 'openai', models: [], success: false,
        discovered_count: 0, last_synced_at: null,
        used_static_fallback: true, error_kind: 'configuration',
        message: '该服务商尚未配置 API Key，请先在设置中填写后再获取模型',
      },
    })
    await openModelManagement()
    const modal = document.querySelector('.nr-modal-wide') as HTMLElement
    const discoverBtn = [...(modal.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)].find((b) => (b.textContent || '').trim() === '发现模型')!
    discoverBtn.click()
    await flushPromises()
    expect(message.warning).toHaveBeenCalledWith(
      expect.stringContaining('请先在设置中填写'),
    )
    expect(message.warning).not.toHaveBeenCalledWith(
      expect.stringContaining('实例未就绪'),
    )
  })
})
