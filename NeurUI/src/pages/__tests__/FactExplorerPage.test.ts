/**
 * FactExplorerPage — UI-1 事实浏览契约测试。
 *
 * 契约面：
 * - query 动词走 /access/query（B3 首个仓内消费者）并渲染结果行；
 * - asOf/knownAt 是两个独立控件（§15.4：不合并不下拉），设置后显示
 *   asOf/knownAt 随 query 一起发送，按轴走事实层；
 * - 事实详情打开后取解释链（/ontology/derivations/{fact_id}），derived=false
 *   显示「观察事实」徽标，不伪造推导；
 * - use 动词仅管理员提示。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const authUser: { id: string; username: string; role: string } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
;(globalThis as Record<string, unknown>).__factExplorerAuthUser = authUser

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__factExplorerAuthUser
    },
  }),
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({
    agentId: { value: 'a1' },
    currentAgent: { value: { name: 'AgentX' } },
    agentLoading: { value: false },
  }),
}))

vi.mock('@/api/modules/ontology', () => ({
  accessQuery: vi.fn(),
  accessAnalyze: vi.fn(),
  accessValidate: vi.fn(),
  accessUse: vi.fn(),
  getDerivationChain: vi.fn(),
  getOntologySchema: vi.fn(),
  listOntologyTerms: vi.fn(),
  listRelationCandidates: vi.fn(),
  createOntologyTerm: vi.fn(),
  updateOntologyTerm: vi.fn(),
  deleteOntologyTerm: vi.fn(),
  approveRelationCandidate: vi.fn(),
  rejectRelationCandidate: vi.fn(),
  resolveOntologyIri: vi.fn(),
  runOntologyPipeline: vi.fn(),
  getOntologyPipelineDiff: vi.fn(),
  exportOntologyTtl: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import { message } from 'ant-design-vue'
import { accessQuery, accessUse, getDerivationChain } from '@/api/modules/ontology'
import FactExplorerPage from '@/pages/FactExplorerPage.vue'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const queryMock = accessQuery as unknown as ReturnType<typeof vi.fn>
const useMock = accessUse as unknown as ReturnType<typeof vi.fn>
const derivationMock = getDerivationChain as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { actions: '操作', noData: '暂无数据' },
    },
  },
})

const queryResult = [
  {
    id: 'fact-001',
    title: '订单D01 is_a HighRiskOrder',
    content: '推导事实示例',
    source: 'graph_bridge',
    created_at: 1730000000,
    metadata: { confidence: 0.92, qualifier: { shape: 'conjunction' } },
  },
  {
    id: 'entry-002',
    title: '普通条目',
    content: '观察事实示例',
    created_at: 1730000001,
  },
]

const mountPage = () =>
  mount(FactExplorerPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-alert': { props: ['message'], template: '<div class="stub-alert">{{ message }}</div>' },
        'a-input': {
          props: ['value', 'type'],
          emits: ['update:value'],
          template: '<input class="stub-input" :type="type" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-input-search': {
          props: ['value'],
          emits: ['update:value', 'search'],
          template: '<input class="stub-search" :value="value" @input="$emit(\'update:value\', $event.target.value)" @keydown.enter="$emit(\'search\')" />',
        },
        'a-select': { props: ['value'], emits: ['update:value'], template: '<select class="stub-select"><slot /></select>' },
        'a-select-option': { template: '<option><slot /></option>' },
        'a-textarea': { props: ['value'], emits: ['update:value'], template: '<textarea class="stub-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-tabs': { props: ['activeKey'], emits: ['update:activeKey'], template: '<div class="stub-tabs"><slot /></div>' },
        'a-tab-pane': { props: ['tab'], template: '<div class="stub-tab-pane"><slot /></div>' },
        'a-drawer': {
          props: ['open', 'title'],
          emits: ['update:open'],
          template: '<div v-if="open" class="stub-drawer"><slot /></div>',
        },
        'a-button': { template: '<button class="stub-a-btn"><slot /></button>' },
        GlassPanel: { template: '<div class="stub-panel"><slot /></div>' },
        GlassButton: {
          props: ['loading', 'disabled', 'variant'],
          emits: ['click'],
          template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
        KnowledgeLineageDrawer: { props: ['open', 'factId'], template: '<div class="stub-lineage" />' },
      },
    },
  })

beforeEach(() => {
  queryMock.mockReset()
  useMock.mockReset()
  derivationMock.mockReset()
  ;(message.success as ReturnType<typeof vi.fn>).mockClear()
  ;(message.error as ReturnType<typeof vi.fn>).mockClear()
  authUser.role = 'admin'
  queryMock.mockResolvedValue({ code: 0, message: 'ok', data: queryResult })
  useMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { fact_id: 'fact-001', outcome: 'adopted' },
  })
  derivationMock.mockResolvedValue({
    code: 0,
    message: 'success',
    data: {
      fact_id: 'fact-001',
      derived: false,
      rule_id: '',
      rule_version: '',
      premise_count: 0,
      premises: [],
      confidence: 0.92,
      derivation_kind: '',
    },
  })
})

describe('FactExplorerPage（UI-1）', () => {
  it('query 动词：结果渲染且请求走 /access/query 可见域检索', async () => {
    const wrapper = mountPage()
    const input = wrapper.find('[data-testid="fact-query-input"]')
    await input.setValue('高风险订单')
    await wrapper.find('[data-testid="fact-query-btn"]').trigger('click')
    await flushPromises()
    expect(queryMock).toHaveBeenCalledTimes(1)
    expect(queryMock.mock.calls[0][0]).toEqual({ query: '高风险订单' })
    expect(queryMock.mock.calls[0][1]).toEqual({ agent_id: 'a1', scope: 'all' })
    const count = wrapper.find('[data-testid="fact-result-count"]')
    expect(count.text()).toContain('2')
    expect(wrapper.text()).toContain('订单D01 is_a HighRiskOrder')
  })

  it('双时态：asOf/knownAt 两个独立控件，并随 query 一起发送', async () => {
    const wrapper = mountPage()
    expect(wrapper.find('[data-testid="fact-asof"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="fact-knownat"]').exists()).toBe(true)
    await wrapper.find('[data-testid="fact-query-input"]').setValue('高风险')
    await wrapper.find('[data-testid="fact-asof"]').setValue('2026-11-01')
    await wrapper.find('[data-testid="fact-knownat"]').setValue('2026-11-02')
    await wrapper.find('[data-testid="fact-query-btn"]').trigger('click')
    await flushPromises()
    expect(queryMock.mock.calls[0][0]).toEqual({
      query: '高风险', asOf: '2026-11-01', knownAt: '2026-11-02',
    })
    expect(Object.keys(queryMock.mock.calls[0][1] as object).sort()).toEqual(['agent_id', 'scope'])
  })

  it('事实详情：观察事实显示观察徽标，不伪造推导', async () => {
    const wrapper = mountPage()
    await wrapper.find('[data-testid="fact-query-input"]').setValue('x')
    await wrapper.find('[data-testid="fact-query-btn"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('tbody tr')[0].trigger('click')
    await flushPromises()
    const badge = wrapper.find('[data-testid="derivation-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('观察事实')
    // derived=false ⇒ 无解释链块
    expect(wrapper.find('[data-testid="explain-chain"]').exists()).toBe(false)
  })

  it('use 动词（管理员）：调用 /access/use/{fact_id} 并提示成功', async () => {
    const wrapper = mountPage()
    // tabs stub 渲染全部分支内容：use 输入直接可用
    await wrapper.find('[data-testid="fact-use-input"]').setValue('fact-001')
    await wrapper.find('[data-testid="fact-use-btn"]').trigger('click')
    await flushPromises()
    expect(useMock).toHaveBeenCalledWith('fact-001', { outcome: 'adopted' })
    expect(message.success).toHaveBeenCalled()
  })

  it('权限态：非管理员 use 分支仍显示仅管理员提示（治理门与后端 403 同源）', () => {
    authUser.role = 'user'
    const wrapper = mountPage()
    expect(wrapper.text()).toContain('仅管理员')
  })
})
