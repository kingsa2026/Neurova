/**
 * ModelPage onMounted 卸载守卫回归测试（F-11）。
 *
 * 缺陷：onMounted 串行 4 段请求无卸载守卫，快速切页后失败在别的页面弹 toast。
 * 修复契约：
 * - 组件卸载（isDisposed）后到达的加载失败不弹 toast；
 * - 未卸载时加载失败仍弹 toast（守卫不得掩盖真错误）；
 * - 卸载后 onMounted 的后续加载段不再发起。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// ─── API mocks（信封形状与后端一致）───
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
  listModels: vi.fn(),
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
import { listProviders, getActiveModel } from '@/api/modules/providers'
import { listModels } from '@/api/modules/models'
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
  return mount(ModelPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

describe('ModelPage — onMounted 卸载守卫（F-11 回归）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(listProviders as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] })
    ;(getActiveModel as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('未卸载时加载失败仍弹 toast（守卫不掩盖真错误）', async () => {
    ;(listModels as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(message.error).toHaveBeenCalled()
  })

  it('卸载后到达的加载失败不弹 toast，且不再发起后续加载段', async () => {
    let rejectModels!: (e: Error) => void
    ;(listModels as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((_resolve, reject) => { rejectModels = reject }),
    )
    const wrapper = mountPage()
    await flushPromises() // fetchProviders 完成，fetchModels 挂起
    expect(message.error).not.toHaveBeenCalled()
    wrapper.unmount() // isDisposed = true
    rejectModels(new Error('boom'))
    await flushPromises()
    // 修复前：卸载后 fetchModels/fetchActiveModel 的 catch 仍会 message.error
    expect(message.error).not.toHaveBeenCalled()
  })

  it('卸载后 onMounted 不再发起后续请求（fetchActiveModel 不被调用）', async () => {
    let resolveProviders!: (v: unknown) => void
    ;(listProviders as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((resolve) => { resolveProviders = resolve }),
    )
    const wrapper = mountPage()
    await flushPromises()
    wrapper.unmount()
    resolveProviders({ data: [] })
    await flushPromises()
    expect(listModels).not.toHaveBeenCalled()
    expect(getActiveModel).not.toHaveBeenCalled()
  })
})
