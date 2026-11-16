/**
 * 3.6-8 审计收口（R5）：MemoryPage 分页为装饰——表格 pagination 声称远端
 * total/current/翻页，但后端 GET /memory 只有 limit 无 offset（memory/crud.py:38，
 * count=len(memories)=当次条数），onTableChange 翻页只重发同参请求，第 2 页数据
 * 不变；showTotal 还是英文 'items' 硬编码。
 * 修后：远端假分页退役（去 current/@change/showSizeChanger），antd 对当前
 * dataSource 做本地分页——不假装有全量游标。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, h } from 'vue'

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'default' }, currentAgent: { value: { name: 'A' } } }),
}))

const { getMemoriesMock } = vi.hoisted(() => ({ getMemoriesMock: vi.fn() }))

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual: Record<string, unknown> = await importOriginal()
  return { ...actual, getMemories: getMemoriesMock }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: 'admin' } }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import MemoryPage from '../MemoryPage.vue'

// a-table 桩透传 pagination props 并支持触发 change 事件
const ATableStub = defineComponent({
  name: 'ATableStub',
  props: ['columns', 'dataSource', 'pagination', 'loading', 'rowKey'],
  emits: ['change'],
  setup(props) {
    return () =>
      h(
        'div',
        { class: 'table-stub', 'data-pag': JSON.stringify(props.pagination ?? null) },
        `rows:${(props.dataSource as unknown[] | undefined)?.length ?? 0}`,
      )
  },
})

const passthrough = { template: '<div><slot /></div>' }
const antStubs = Object.fromEntries(
  ['a-tabs', 'a-tab-pane', 'a-input-search', 'a-select', 'a-select-option', 'a-checkbox',
    'a-button', 'a-tag', 'a-tooltip', 'a-list', 'a-empty', 'a-input-number',
    'a-popconfirm', 'a-alert', 'a-spin'].map((name) => [name, passthrough]),
)

const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, fallbackWarn: false, messages: { 'zh-CN': {} } })

const mountPage = () =>
  mount(MemoryPage, {
    global: {
      plugins: [i18n],
      stubs: { ATable: ATableStub, GlassCard: passthrough, GlassButton: passthrough, ...antStubs },
    },
  })

function fixtureRows(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: `m${i}`, content: `内容${i}`, type: 'semantic', origin: 'agent', created_at: '2026-11-01', importance: 0.5,
  }))
}

describe('MemoryPage — 3.6-8 分页诚实化', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMemoriesMock.mockResolvedValue({
      code: 0,
      data: { count: 15, memories: fixtureRows(15) },
    })
  })

  const paginationOf = (wrapper: ReturnType<typeof mountPage>) => {
    const stub = wrapper.find('.table-stub')
    return JSON.parse(stub.attributes('data-pag') ?? 'null') as Record<string, unknown> | null
  }

  it('表格 pagination 不再声称远端游标（无 current/total/showSizeChanger）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const pag = paginationOf(wrapper)
    expect(pag).toBeTruthy()
    expect(pag).not.toHaveProperty('current')
    expect(pag).not.toHaveProperty('total')
    expect(pag?.showSizeChanger).toBe(false)
  })

  it('表格翻页事件不再重发同参请求（后端无 offset，重发即假交互）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const callsBefore = getMemoriesMock.mock.calls.length
    ;(wrapper.findComponent(ATableStub).vm as any).$emit('change', { current: 2, pageSize: 10 })
    await flushPromises()
    expect(getMemoriesMock.mock.calls.length).toBe(callsBefore)
  })
})
