import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

/**
 * P1-24（审计 2026-11-16）：ModelPage addNewModel 把同一对象 unshift 两次——
 * `openModelManagement` 把 modelTarget 指向 v-for 元素本体（providers 列表元素），
 * `modelTarget.value.models.unshift(newModel)` 与 `live.models.unshift(newModel)`
 * 打在**同一个数组**上（live === modelTarget.value），model_count 同理 ++ 两次。
 * 症状：卡片计数虚高（刷新后与后端对账又缩回去）、defaultModelOptions 出重复行。
 *
 * 驱动真实 UI 链：服务商卡「模型」→ 弹窗「添加模型」→ 填 ID → 提交。
 */
vi.mock('@/api/modules/providers', () => ({
  listProviders: vi.fn().mockResolvedValue({ data: [] }),
  getActiveModel: vi.fn().mockResolvedValue({ data: {} }),
  activateModel: vi.fn().mockResolvedValue({ data: null }),
  updateProvider: vi.fn().mockResolvedValue({ data: null }),
  createProvider: vi.fn().mockResolvedValue({ data: null }),
  deleteProvider: vi.fn().mockResolvedValue({ data: null }),
  discoverModels: vi.fn(),
  discoverModelsStructured: vi.fn(),
  mergeDiscoveredModels: vi.fn(),
  filterProviderModels: vi.fn(),
  getProviderSeries: vi.fn().mockResolvedValue({ data: [] }),
  testConnection: vi.fn(),
}))
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn(),
  updateModel: vi.fn().mockResolvedValue({ data: null }),
  deleteModel: vi.fn().mockResolvedValue({ data: null }),
  detectCapabilities: vi.fn(),
  checkModelConnection: vi.fn(),
  probeModelMultimodal: vi.fn(),
  probeOutputLimit: vi.fn(),
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
import { listProviders, updateProvider } from '@/api/modules/providers'
import { listModels } from '@/api/modules/models'

const messages = {
  common: { search: '搜索', cancel: '取消', save: '保存', success: '成功', error: '失败', close: '关闭', confirm: '确认', add: '添加', delete: '删除', edit: '编辑', clear: '清空', name: '名称' },
  model: {
    searchProviders: '搜索提供商…', searchModels: '搜索模型…',
    title: '模型管理', providers: '服务商', models: '模型', settings: '设置', testConnection: '测试连接',
    connectionOk: '连接成功 {ms}', connectionFailed: '连接失败',
    modelManagement: '模型管理', discover: '发现模型', detectCaps: '检测能力', detectCapsTip: '检测',
    baseUrl: 'Base URL', apiKey: 'API Key', authMethod: '鉴权方式', genParams: '生成参数', genParamsDesc: 'JSON',
    advanced: '高级', headers: '请求头', addModel: '添加模型', modelId: '模型 ID',
    modelCount: '{n} 模型', noModels: '暂无模型',
    testConnectionTip: '测连', probeMultimodalTip: '多模态', probeOutputLimitTip: '输出上限', probeOutputValue: '{value}',
    editModel: '编辑模型', userAdded: '手动添加', freeModels: '免费', builtin: '内置',
  },
  nav: {},
  ui: { providerNsc: '国家超算互联网', providerSensetime: '商汤', providerXiaomi: '小米', text: '文本', egModelId: '如 gpt-x', egModelName: '显示名' },
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div><slot name="header"/><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading', 'title'], emits: ['click'], template: '<button :title="title" @click="$emit(\'click\')"><slot/></button>' },
  'a-select': { props: ['value'], template: '<select/>' },
  'a-switch': { template: '<button class="ant-switch" />' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-badge': { template: '<span><slot/></span>' },
  'a-tooltip': { template: '<span><slot/></span>' },
  'a-popconfirm': { template: '<span><slot/></span>' },
  'a-collapse': { template: '<div><slot/></div>' },
  'a-collapse-panel': { template: '<div><slot/></div>' },
  Teleport: { template: '<div><slot/></div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, messages: { 'zh-CN': messages } })
  return mount(ModelPage, { global: { plugins: [i18n], stubs: globalStubs }, attachTo: document.body })
}

function findBtn(text: string): HTMLButtonElement | undefined {
  return [...document.body.querySelectorAll('button')].find(
    (b) => (b.textContent || '').trim() === text,
  ) as HTMLButtonElement | undefined
}

async function addModelViaUi(modelId: string) {
  // 服务商卡「模型」按钮打开管理弹窗（modelTarget 指向列表元素本体）
  const cards = [...document.querySelectorAll('.nr-pv-card')]
  const card = cards.find((c) => (c.textContent || '').includes('Ollama'))
  if (!card) throw new Error('Ollama card not found')
  const modelsBtn = [...card.querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '模型')
  if (!modelsBtn) throw new Error('models button not found')
  modelsBtn.click()
  await flushPromises()

  const addTrigger = document.body.querySelector('.nr-mm-add-trigger') as HTMLButtonElement | null
  if (!addTrigger) throw new Error('add trigger not found')
  addTrigger.click()
  await flushPromises()

  const idInput = document.body.querySelector('.nr-mm-add-form input.nr-input') as HTMLInputElement | null
  if (!idInput) throw new Error('model id input not found')
  idInput.value = modelId
  idInput.dispatchEvent(new Event('input'))
  await flushPromises()

  const submit = document.body.querySelector('.nr-mm-btn-submit') as HTMLButtonElement | null
  if (!submit) throw new Error('submit button not found')
  submit.click()
  await flushPromises()
}

describe('ModelPage — addNewModel 单次入列（P1-24）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listProviders).mockResolvedValue({ data: [] } as never)
    vi.mocked(listModels).mockResolvedValue({
      data: [{ model_id: 'existing-1', name: 'Existing One', provider: 'ollama' }],
    } as never)
    vi.mocked(updateProvider).mockResolvedValue({ data: null } as never)
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('新增模型后卡片计数与弹窗列表各只出现一次', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await addModelViaUi('brand-new-model')

    expect(updateProvider).toHaveBeenCalledWith(
      'ollama',
      expect.objectContaining({ config: expect.objectContaining({ add_model: 'brand-new-model' }) }),
    )

    // 卡片计数：existing-1 + brand-new-model = 2（bug 下 model_count 被 ++ 两次 → 3 模型）
    const cards = [...document.querySelectorAll('.nr-pv-card')]
    const ollamaCard = cards.find((c) => (c.textContent || '').includes('Ollama'))
    expect(ollamaCard?.textContent || '').toContain('2 模型')

    // 弹窗列表：两行（existing + new），无重复行
    const modal = document.body.querySelector('.nr-mm-list')
    expect(modal).toBeTruthy()
    const items = [...(modal as HTMLElement).querySelectorAll('.nr-mm-item')]
    expect(items).toHaveLength(2)
    const ids = items.map((el) => el.querySelector('.nr-mm-item-id')?.textContent?.trim())
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toContain('brand-new-model')
  })
})
