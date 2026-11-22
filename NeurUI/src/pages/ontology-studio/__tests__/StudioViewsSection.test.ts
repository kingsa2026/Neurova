// U7 三视图分区包装：子导航渲染＋切换挂载对应只读视图（接线断言）。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import StudioViewsSection from '../StudioViewsSection.vue'
import {
  accessQuery,
  getDerivationChain,
  listOntologyDecisions,
  traceOntologyDecision,
} from '@/api/modules/ontology'

vi.mock('@/api/modules/ontology', () => ({
  listOntologyDecisions: vi.fn(),
  traceOntologyDecision: vi.fn(),
  accessQuery: vi.fn(),
  getDerivationChain: vi.fn(),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { loading: '加载中...', search: '搜索', clear: '清除' },
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
        genealogyTitle: '推导谱系',
        genealogyRefresh: '刷新',
        genealogyEmpty: '暂无事实，请先检索事实库',
        genealogyLoadFailed: '推导谱系加载失败',
        genealogyFactLabel: '选择事实',
        genealogyObserved: '观察事实',
        genealogyDerived: '推导事实',
        genealogyNoDerivation: '该事实无推导边（观察事实）',
        timelineTitle: '双时态时间线',
        timelineRefresh: '刷新',
        timelineEmpty: '暂无事实区间',
        timelineLoadFailed: '双时态时间线加载失败',
        timelineNow: '当前时刻',
        timelineOpenEnd: '生效中（未闭合）',
        timelineNoStart: '起点未记录',
        asOfLabel: 'asOf（业务时间）',
      },
    },
  },
})

const STUBS = {
  'a-alert': { props: ['message'], template: '<div class="ant-alert">{{ message }}</div>' },
  'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
  'a-select': {
    props: ['value', 'options'],
    emits: ['update:value', 'change'],
    template: `<div class="a-select-stub"><button v-for="o in options" :key="o.value" :data-value="o.value" @click="$emit('update:value', o.value); $emit('change', o.value)">{{ o.label }}</button></div>`,
  },
}

function mountSection() {
  return mount(StudioViewsSection, {
    global: { plugins: [i18n], stubs: STUBS },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listOntologyDecisions).mockResolvedValue({ code: 0, data: [], request_id: '' } as never)
  vi.mocked(traceOntologyDecision).mockResolvedValue({ code: 0, data: { decision_id: '', direction: 'both', chain: [] }, request_id: '' } as never)
  vi.mocked(accessQuery).mockResolvedValue([] as never)
  vi.mocked(getDerivationChain).mockRejectedValue(new Error('404'))
})

describe('StudioViewsSection', () => {
  it('renders the three read-only view tabs', () => {
    const wrapper = mountSection()
    const text = wrapper.text()
    expect(text).toContain('决策因果图')
    expect(text).toContain('推导谱系')
    expect(text).toContain('双时态时间线')
  })

  it('mounts the decision graph by default and switches on tab click', async () => {
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.find('[data-testid="studio-decision-graph"]').exists()).toBe(true)
    await wrapper.find('[data-testid="views-nav-genealogy"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="studio-derivation-genealogy"]').exists()).toBe(true)
    await wrapper.find('[data-testid="views-nav-timeline"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="studio-bitemporal-timeline"]').exists()).toBe(true)
  })
})
