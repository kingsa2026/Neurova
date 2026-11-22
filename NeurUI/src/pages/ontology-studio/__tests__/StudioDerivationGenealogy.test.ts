// U7 推导谱系（只读视图）：access/query 选根事实 + derivations 逐层展开
// premises→conclusion 分层 DAG；mock 网络层，断言节点/边数量与三态。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import StudioDerivationGenealogy from '../StudioDerivationGenealogy.vue'
import { accessQuery, getDerivationChain } from '@/api/modules/ontology'

vi.mock('@/api/modules/ontology', () => ({
  accessQuery: vi.fn(),
  getDerivationChain: vi.fn(),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { loading: '加载中...', search: '搜索' },
      ontology: {
        genealogyTitle: '推导谱系',
        genealogyRefresh: '刷新',
        genealogyEmpty: '暂无事实，请先检索事实库',
        genealogyLoadFailed: '推导谱系加载失败',
        genealogyFactLabel: '选择事实',
        genealogyObserved: '观察事实',
        genealogyDerived: '推导事实',
        genealogyNoDerivation: '该事实无推导边（观察事实）',
        graphNodes: '节点',
        graphEdges: '边',
      },
    },
  },
})

function fact(knowledgeId: string, title: string) {
  return {
    id: knowledgeId, knowledge_id: knowledgeId, title, content: '',
    created_at: 0, metadata: {},
  }
}

const FACTS = [fact('fact_root', '客户A·is_a·VIP'), fact('fact_p1', ''), fact('fact_p2', '')]

const CHAINS: Record<string, Record<string, unknown>> = {
  fact_root: {
    fact_id: 'fact_root', derived: true, rule_id: 'r_vip', rule_version: 'v1',
    premise_count: 2, confidence: 0.8, derivation_kind: 'relay',
    premises: [
      { premise_fact_id: 'fact_p1', rule_id: 'r_vip', rule_version: 'v1' },
      { premise_fact_id: 'fact_p2', rule_id: 'r_vip', rule_version: 'v1' },
    ],
  },
  fact_p1: {
    fact_id: 'fact_p1', derived: false, rule_id: '', rule_version: '',
    premise_count: 0, confidence: 1, derivation_kind: '', premises: [],
  },
  fact_p2: {
    fact_id: 'fact_p2', derived: false, rule_id: '', rule_version: '',
    premise_count: 0, confidence: 1, derivation_kind: '', premises: [],
  },
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

function mountGenealogy() {
  return mount(StudioDerivationGenealogy, {
    global: { plugins: [i18n], stubs: STUBS },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(accessQuery).mockResolvedValue(FACTS as never)
  vi.mocked(getDerivationChain).mockImplementation((factId: string) => {
    const chain = CHAINS[factId]
    return chain
      ? Promise.resolve({ code: 0, data: chain, request_id: '' } as never)
      : Promise.reject(new Error(`404 ${factId}`))
  })
})

describe('StudioDerivationGenealogy', () => {
  it('builds layered premises→conclusion DAG from the derivation ledger', async () => {
    const wrapper = mountGenealogy()
    await flushPromises()
    const nodes = wrapper.findAll('[data-testid="genealogy-node"]')
    const edges = wrapper.findAll('[data-testid="genealogy-edge"]')
    expect(nodes).toHaveLength(3) // 根结论 + 两个前提
    expect(edges).toHaveLength(2) // p1→root, p2→root
    const root = wrapper.find('[data-testid="genealogy-node"][data-fact-id="fact_root"]')
    expect(root.exists()).toBe(true)
    expect(root.attributes('data-depth')).toBe('0')
    // 事实层命中：access/query 走 knownAt 快照（knowledge_id＝fact_id）
    const body = vi.mocked(accessQuery).mock.calls[0][0] as { knownAt?: string }
    expect(body.knownAt).toBeTruthy()
    expect(wrapper.find('[data-testid="genealogy-observed-note"]').exists()).toBe(false)
  })

  it('shows observed-note and a single node when the root fact has no derivation', async () => {
    vi.mocked(getDerivationChain).mockResolvedValue({
      code: 0,
      data: { fact_id: 'fact_root', derived: false, rule_id: '', rule_version: '', premise_count: 0, premises: [], confidence: 1, derivation_kind: '' },
      request_id: '',
    } as never)
    const wrapper = mountGenealogy()
    await flushPromises()
    expect(wrapper.find('[data-testid="genealogy-observed-note"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="genealogy-node"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid="genealogy-edge"]')).toHaveLength(0)
  })

  it('shows empty state when the fact store returns nothing', async () => {
    vi.mocked(accessQuery).mockResolvedValue([] as never)
    const wrapper = mountGenealogy()
    await flushPromises()
    expect(wrapper.find('[data-testid="genealogy-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无事实')
  })

  it('shows error state when the fact query fails', async () => {
    vi.mocked(accessQuery).mockRejectedValue(new Error('boom'))
    const wrapper = mountGenealogy()
    await flushPromises()
    expect(wrapper.find('[data-testid="genealogy-error"]').exists()).toBe(true)
  })

  it('shows loading state while facts are in flight', async () => {
    vi.mocked(accessQuery).mockReturnValue(new Promise(() => {}) as never)
    const wrapper = mountGenealogy()
    await flushPromises()
    expect(wrapper.find('[data-testid="genealogy-loading"]').exists()).toBe(true)
  })

  it('treats derivation read failures as observed facts instead of fabricating a chain', async () => {
    vi.mocked(getDerivationChain).mockRejectedValue(new Error('404'))
    const wrapper = mountGenealogy()
    await flushPromises()
    expect(wrapper.find('[data-testid="genealogy-observed-note"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="genealogy-node"]')).toHaveLength(1)
  })
})
