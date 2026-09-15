/**
 * 回归 2026-09-14：获取模型 ≠ 添加模型。
 *
 * 契约：点「发现模型」只渲染"可添加的模型"候选面板（.nr-mm-candidate），
 * 不得把新模型直接并进模型列表；用户点候选行「添加」才调用
 * POST /discover/merge（mergeDiscoveredModels）并入配置。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const listProviders = vi.fn()
const listModels = vi.fn()
const discoverModelsStructured = vi.fn()
const mergeDiscoveredModels = vi.fn()

vi.mock('@/api/modules/providers', () => ({
  listProviders: (...a: any[]) => listProviders(...a),
  getActiveModel: vi.fn().mockResolvedValue({ data: {} }),
  activateModel: vi.fn().mockResolvedValue({ data: null }),
  updateProvider: vi.fn().mockResolvedValue({ data: null }),
  createProvider: vi.fn().mockResolvedValue({ data: null }),
  deleteProvider: vi.fn().mockResolvedValue({ data: null }),
  discoverModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
  discoverModelsStructured: (...a: any[]) => discoverModelsStructured(...a),
  mergeDiscoveredModels: (...a: any[]) => mergeDiscoveredModels(...a),
  filterProviderModels: vi.fn().mockResolvedValue({ data: { models: [] } }),
  getProviderSeries: vi.fn().mockResolvedValue({ data: { series: [] } }),
  testConnection: vi.fn(),
}))
vi.mock('@/api/modules/models', () => ({
  listModels: (...a: any[]) => listModels(...a),
  updateModel: vi.fn().mockResolvedValue({ data: null }),
  deleteModel: vi.fn().mockResolvedValue({ data: null }),
  detectCapabilities: vi.fn().mockResolvedValue({ data: { detected: 0, results: [] } }),
  checkModelConnection: vi.fn(),
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
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

import ModelPage from '../ModelPage.vue'

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存', success: '成功', error: '失败', confirm: '确认' },
  model: {
    modelManagement: '模型管理', models: '模型', discover: '发现模型',
    detectCaps: '检测能力', detectCapsTip: '检测',
    noNewModels: '没有发现新模型', modelsDiscovered: '发现 {n} 个新模型',
    discoverFailed: '发现模型失败',
    discoverAddable: '可添加的模型', addAll: '全部添加', addFiltered: '添加',
    searchModels: '搜索', addModel: '添加模型', editModel: '编辑', delete: '删除',
    settings: '设置', testConnectionTip: '测试', probeMultimodalTip: '探测',
    userAdded: '手动', freeModels: '免费', builtin: '内置', save: '保存',
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

/** 打开 openai 服务商的模型管理弹窗并点「发现模型」。 */
async function openManagementAndDiscover() {
  const wrapper = mountPage()
  await flushPromises()
  const card = [...document.querySelectorAll('.nr-pv-card')].find((c) => (c.textContent || '').includes('OpenAI'))
  expect(card, '应有 OpenAI 内置服务商卡').toBeTruthy()
  ;(card!.querySelector('.nr-pv-actions .nr-action-btn.primary') as HTMLButtonElement).click()
  await flushPromises()
  const modal = [...document.querySelectorAll('.nr-modal-wide')]
  expect(modal.length, '应打开模型管理弹窗').toBeGreaterThan(0)
  const discoverBtn = [...modal[0].querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '发现模型')
  expect(discoverBtn, '弹窗内应有发现模型按钮').toBeTruthy()
  discoverBtn!.click()
  await flushPromises()
  return wrapper
}

describe('ModelPage — 发现候选必须手动添加（回归 2026-09-14）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listProviders.mockResolvedValue({
      data: [{ provider_id: 'openai', name: 'OpenAI', api_key: 'sk-test', models: [{ id: 'gpt-4o', name: 'GPT-4o' }] }],
    })
    listModels.mockResolvedValue({ data: [{ model_id: 'gpt-4o', name: 'GPT-4o', provider: 'openai' }] })
    discoverModelsStructured.mockResolvedValue({
      code: 0,
      data: {
        provider_id: 'openai',
        models: [
          { id: 'gpt-4o', name: 'GPT-4o' },
          { id: 'gpt-5', name: 'GPT-5' },
        ],
        success: true,
        discovered_count: 1,
        last_synced_at: '2026-09-14T00:00:00',
        used_static_fallback: false,
        error_kind: null,
        message: '',
      },
    })
    mergeDiscoveredModels.mockResolvedValue({ code: 0, data: { provider_id: 'openai', merged_count: 1 } })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('点发现模型只出候选面板，不自动添加、不调 merge', async () => {
    await openManagementAndDiscover()
    // 未发生任何"添加"动作
    expect(mergeDiscoveredModels, '发现阶段不得调用 merge').not.toHaveBeenCalled()
    // 候选面板存在且只含未配置的 gpt-5（gpt-4o 已在配置中）
    const rows = [...document.querySelectorAll('.nr-mm-candidate')]
    expect(rows.length, '应恰好 1 行候选').toBe(1)
    expect(rows[0].textContent).toContain('gpt-5')
    expect(rows[0].textContent).not.toContain('gpt-4o')
    // 主模型列表仍只有 gpt-4o
    const listRows = [...document.querySelectorAll('.nr-mm-list .nr-mm-item')]
    expect(listRows.length).toBe(1)
    expect(listRows[0].textContent).toContain('gpt-4o')
  })

  it('点候选行「添加」才调 merge 并入该模型', async () => {
    await openManagementAndDiscover()
    const row = document.querySelector('.nr-mm-candidate')!
    const addBtn = [...row.querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '添加')
    expect(addBtn, '候选行应有添加按钮').toBeTruthy()
    addBtn!.click()
    await flushPromises()
    expect(mergeDiscoveredModels).toHaveBeenCalledWith('openai', ['gpt-5'])
  })
})
