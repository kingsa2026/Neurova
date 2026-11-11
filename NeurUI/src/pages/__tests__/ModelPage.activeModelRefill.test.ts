/**
 * 模型管理页"系统默认模型"读回回归（用户报障：保存成功，刷新后提供商显示、模型空）。
 *
 * 根因：onMounted 尾部的 `watch(() => defaultConfig.provider_id, () => { model_id = '' })`
 * 与 `@change="onDefaultProviderChange"`（用户手动换 provider 时清 model 重选）
 * 是同一意图的两份实现，且 watch 口径过宽——fetchActiveModel 的**程序化回填**
 * （先填 provider_id 再填 model_id，同一 tick）也会触发它，tick 末尾把刚填的
 * model_id 清掉。用户看到：提供商在、模型空。
 *
 * 修复契约：读回回填完成后 provider 与 model 两个选择器都有值；
 * 用户手动换 provider 仍清 model（@change 语义保留，watch 退役）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

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
import { listProviders, getActiveModel } from '@/api/modules/providers'
import { listModels } from '@/api/modules/models'

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存', success: '成功', error: '失败', close: '关闭', confirm: '确认', add: '添加', delete: '删除', edit: '编辑' },
  model: {
    searchProviders: '搜索提供商…',
    title: '模型管理', providers: '服务商', models: '模型', settings: '设置', testConnection: '测试连接',
    connectionOk: '连接成功 {ms}', connectionFailed: '连接失败',
    modelManagement: '模型管理', discover: '发现模型', detectCaps: '检测能力', detectCapsTip: '检测',
    baseUrl: 'Base URL', apiKey: 'API Key', authMethod: '鉴权方式', genParams: '生成参数', genParamsDesc: 'JSON',
    advanced: '高级', headers: '请求头', addModel: '添加模型',
    defaultProvider: '默认服务商', defaultModel: '默认模型', active: '当前',
  },
  nav: {},
  ui: { providerNsc: '国家超算互联网', providerSensetime: '商汤', providerXiaomi: '小米' },
}

// a-select stub 渲染 value，供断言"选择器显示的是什么"
const globalStubs = {
  GlassCard: { props: ['title'], template: '<div><slot name="header"/><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading', 'title'], emits: ['click'], template: '<button :title="title" @click="$emit(\'click\')"><slot/></button>' },
  'a-select': { props: ['value'], template: '<select class="a-select-stub" :data-value="value === undefined || value === null ? \'\' : String(value)"><slot/></select>' },
  'a-select-option': { props: ['value'], template: '<option :value="value"><slot/></option>' },
  'a-switch': { props: ['checked'], template: '<button class="ant-switch" />' },
  'a-slider': { template: '<input type="range" />' },
  'a-input': { props: ['value', 'placeholder'], template: '<input :value="value" />' },
  'a-input-number': { template: '<input />' },
  'a-input-password': { template: '<input type="password" />' },
  'a-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-badge': { template: '<span><slot/></span>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { template: '<div><label/><slot/></div>' },
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

function selectValues(wrapper: ReturnType<typeof mountPage>): string[] {
  return wrapper.findAll('.a-select-stub').map((s) => s.attributes('data-value') ?? '')
}

describe('ModelPage — 系统默认模型读回（刷新后提供商/模型都要在）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // openrouter：种子 id='openrouter'/name='OpenRouter'；后端 active-model 读回 provider_name
    ;(listProviders as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: [{ provider_id: 'openrouter', name: 'OpenRouter', is_active: true, models_count: 1 }],
    })
    ;(listModels as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: [{ model_id: 'm-free', name: 'Ling Free', provider_id: 'openrouter' }],
    })
    ;(getActiveModel as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { provider_name: 'OpenRouter', model: 'm-free' },
    })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('读回回填后模型选择器必须显示已保存的模型（不被 watch 清空）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const values = selectValues(wrapper)
    expect(values).toContain('openrouter'), '提供商选择器应显示已保存的 provider'
    expect(values).toContain('m-free'), (
      '模型选择器应显示已保存的模型——修复前被 provider watch 在回填 tick 末尾清空')
  })

  it('provider 未加载完时读回不匹配，不产生半填充形态', async () => {
    // getActiveModel 给一个不在列表里的 provider：match 失败 ⇒ 两格都不该被填一半
    ;(getActiveModel as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { provider_name: 'GhostProvider', model: 'm-x' },
    })
    const wrapper = mountPage()
    await flushPromises()

    const values = selectValues(wrapper)
    expect(values).not.toContain('m-x'), '匹配不到 provider 时不得只填模型'
  })
})
