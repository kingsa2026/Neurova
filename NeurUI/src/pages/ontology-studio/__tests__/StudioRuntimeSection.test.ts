// W3 前端运行时分区行为断言（specs/2026-11-12 §14 U1 前两 tab）：
// 渲染＋admin 门（非 admin 写面不可见）＋登记/越界原位回显＋dry 读数结构。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import StudioRuntimeSection from '../StudioRuntimeSection.vue'
import {
  listOntologyFunctions,
  listOntologyStateMachines,
  createOntologyFunction,
} from '@/api/modules/ontology'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/modules/ontology', () => ({
  listOntologyFunctions: vi.fn(),
  listOntologyStateMachines: vi.fn(),
  createOntologyFunction: vi.fn(),
  deleteOntologyFunction: vi.fn(),
  computeOntologyFunction: vi.fn(),
  createOntologyStateMachine: vi.fn(),
  deleteOntologyStateMachine: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: vi.fn(),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ontology: {}, common: { delete: '删除', save: '保存',
    yes: '是', no: '否', actions: '操作' } } },
})

const mockedAuth = vi.mocked(useAuthStore)

function mountSection() {
  return mount(StudioRuntimeSection, {
    global: { plugins: [i18n], stubs: { 'a-alert': true, 'a-table': true, 'a-empty': true, 'a-tag': true, 'a-input': true } },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listOntologyFunctions).mockResolvedValue({ data: [{
    tenant_id: 'default', function_id: 'fn1', label: '', definition: '',
    expr_text: 'sum(facts("stores"))', input_bindings: {}, output_predicate: 'stock',
    scope: {}, materialization: 'observe', enabled: true, version: 'v1' }] } as never)
  vi.mocked(listOntologyStateMachines).mockResolvedValue({ data: [{
    tenant_id: 'default', term_id: 'orders', states: ['created', 'paid'],
    transitions: [{ from: 'created', to: 'paid' }], initial_state: 'created',
    event_bindings: [], enabled: true }] } as never)
})

describe('StudioRuntimeSection', () => {
  it('renders functions and state machines tables', async () => {
    mockedAuth.mockReturnValue({ user: { role: 'admin' } } as never)
    const wrapper = mountSection()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('fn1')
    expect(text).toContain('sum(facts("stores"))')
    expect(text).toContain('created→paid')
    expect(wrapper.find('[data-testid="functions-table"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="states-table"]').exists()).toBe(true)
  })

  it('hides admin write faces from non-admin users', async () => {
    mockedAuth.mockReturnValue({ user: { role: 'user' } } as never)
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.find('[data-testid="fn-register"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="machine-register"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="fn-delete"]').exists()).toBe(false)
  })

  it('surfaces registration compile errors inline', async () => {
    mockedAuth.mockReturnValue({ user: { role: 'admin' } } as never)
    const wrapper = mountSection()
    await flushPromises()
    vi.mocked(createOntologyFunction).mockRejectedValue({
      response: { data: { detail: '表达式含白名单外节点 Attribute' } } })
    await (wrapper.vm as unknown as { submitFunction: () => Promise<void> }).submitFunction()
    await flushPromises()
    expect(wrapper.find('[data-testid="fn-error"]').text())
      .toContain('表达式含白名单外节点 Attribute')
  })
})
