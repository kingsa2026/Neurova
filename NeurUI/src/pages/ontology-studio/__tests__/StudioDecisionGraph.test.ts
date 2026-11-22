// U7 决策因果图（只读视图）：列表/trace 双端点读数渲染＋三态＋焦点切换。
// mock 网络层（API 模块），业务对象不打桩——断言落在渲染出的节点/边数量上。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import StudioDecisionGraph from '../StudioDecisionGraph.vue'
import { listOntologyDecisions, traceOntologyDecision } from '@/api/modules/ontology'

vi.mock('@/api/modules/ontology', () => ({
  listOntologyDecisions: vi.fn(),
  traceOntologyDecision: vi.fn(),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { loading: '加载中...' },
      ontology: {
        decisionGraphTitle: '决策因果图',
        decisionGraphRefresh: '刷新',
        decisionGraphEmpty: '暂无登记决策',
        decisionGraphLoadFailed: '决策因果图加载失败',
        decisionGraphFocus: '焦点决策',
        decisionGraphUpstream: '上游',
        decisionGraphDownstream: '下游',
        graphNodes: '节点',
        graphEdges: '边',
      },
    },
  },
})

function decision(id: string, scenario: string, category = 'routing', confidence = 0.8) {
  return {
    tenant_id: 'default', decision_id: id, owner_id: '', category, scenario,
    reasoning: '', outcome: 'ok', confidence, decision_maker: 'alice', metadata: {},
  }
}

const DECISIONS = [decision('dec_a', '选择检索通道'), decision('dec_b', '写入策略', 'memory'), decision('dec_c', '退避重试', 'runtime')]

const TRACE_A = {
  decision_id: 'dec_a', direction: 'both', chain: [
    { decision_id: 'dec_up', link_kind: 'precedent', side: 'up' },
    { decision_id: 'dec_b', link_kind: 'caused', side: 'down' },
    { decision_id: 'dec_c', link_kind: 'influenced', side: 'down' },
  ],
}

const STUBS = {
  'a-alert': { props: ['message'], template: '<div class="ant-alert">{{ message }}</div>' },
  'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
  'a-select': {
    props: ['value', 'options'],
    emits: ['update:value', 'change'],
    template: `<div class="a-select-stub"><button v-for="o in options" :key="o.value" :data-value="o.value" @click="$emit('update:value', o.value); $emit('change', o.value)">{{ o.label }}</button></div>`,
  },
}

function mountGraph() {
  return mount(StudioDecisionGraph, {
    global: { plugins: [i18n], stubs: STUBS },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listOntologyDecisions).mockResolvedValue({ code: 0, data: DECISIONS, request_id: '' } as never)
  vi.mocked(traceOntologyDecision).mockResolvedValue({ code: 0, data: TRACE_A, request_id: '' } as never)
})

describe('StudioDecisionGraph', () => {
  it('renders focus + closure nodes and labeled edges from list/trace endpoints', async () => {
    const wrapper = mountGraph()
    await flushPromises()
    const nodes = wrapper.findAll('[data-testid="decision-node"]')
    const edges = wrapper.findAll('[data-testid="decision-edge"]')
    expect(nodes).toHaveLength(4) // 焦点 dec_a + 上游 dec_up + 下游 dec_b/dec_c
    expect(edges).toHaveLength(3)
    const kinds = edges.map((e) => e.attributes('data-kind')).sort()
    expect(kinds).toEqual(['caused', 'influenced', 'precedent'])
    expect(wrapper.find('[data-testid="decision-graph-svg"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="decision-graph-stats"]').text()).toContain('4')
    expect(wrapper.find('[data-testid="decision-graph-stats"]').text()).toContain('3')
    // 焦点决策取列表第一条
    expect(traceOntologyDecision).toHaveBeenCalledWith('dec_a', 'both')
  })

  it('shows empty state when the decision ledger is empty', async () => {
    vi.mocked(listOntologyDecisions).mockResolvedValue({ code: 0, data: [], request_id: '' } as never)
    const wrapper = mountGraph()
    await flushPromises()
    expect(wrapper.find('[data-testid="decision-graph-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无登记决策')
    expect(wrapper.find('[data-testid="decision-graph-svg"]').exists()).toBe(false)
  })

  it('shows error state when the list endpoint fails', async () => {
    vi.mocked(listOntologyDecisions).mockRejectedValue(new Error('boom'))
    const wrapper = mountGraph()
    await flushPromises()
    expect(wrapper.find('[data-testid="decision-graph-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('决策因果图加载失败')
  })

  it('shows loading state while the list request is in flight', async () => {
    vi.mocked(listOntologyDecisions).mockReturnValue(new Promise(() => {}) as never)
    const wrapper = mountGraph()
    await flushPromises()
    expect(wrapper.find('[data-testid="decision-graph-loading"]').exists()).toBe(true)
  })

  it('re-fetches the trace when the focus decision changes', async () => {
    const wrapper = mountGraph()
    await flushPromises()
    await wrapper.find('[data-testid="decision-focus-select"] [data-value="dec_b"]').trigger('click')
    await flushPromises()
    expect(traceOntologyDecision).toHaveBeenLastCalledWith('dec_b', 'both')
  })

  it('surfaces trace failure without discarding the node list', async () => {
    vi.mocked(traceOntologyDecision).mockRejectedValue(new Error('boom'))
    const wrapper = mountGraph()
    await flushPromises()
    expect(wrapper.find('[data-testid="decision-trace-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="decision-focus-select"]').exists()).toBe(true)
  })
})
