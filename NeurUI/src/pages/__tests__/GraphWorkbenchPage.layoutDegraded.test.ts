/**
 * 3.6-3 审计收口（R5）：布局降级警示只置位不复位、且在 computed 内写 ref
 * （旧实现 flowNodes computed 内 `layoutDegraded.value = true`，无复位分支——
 * 一次超预算后警示永挂，节点数回落也不消失）。
 * 修后 layoutDegraded 为独立 computed，判据与 forceLayoutFull 内部预算门
 * 同一常量同一比较（LAYOUT_NODE_BUDGET），随数据变化自动复位。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, h, nextTick, ref } from 'vue'

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({
    agentId: ref('agent-1'),
    currentAgent: ref({ id: 'agent-1', name: 'Test Agent' }),
    agentLoading: ref(false),
  }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ currentUser: { id: 'u1', role: 'admin' } }),
}))

const { requestGet } = vi.hoisted(() => ({ requestGet: vi.fn() }))
vi.mock('@/api', () => {
  const request = { get: requestGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { request, default: request }
})

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@vue-flow/core', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    VueFlow: defineComponent({
      name: 'VueFlowStub',
      props: ['nodes', 'edges'],
      emits: ['node-click', 'node-drag-stop'],
      // 必须真实消费 nodes prop：flowNodes computed 是懒求值，渲染路径不读
      // prop 则依赖不建立、computed 不求值（旧实现把置位藏在 computed 副作用里，
      // 正是这类路径敏感的坑）。
      setup(props) {
        return () => h('div', { class: 'vue-flow-stub' }, `nodes:${props.nodes?.length ?? 0}`)
      },
    }),
  }
})
vi.mock('@vue-flow/background', () => ({ Background: defineComponent({ name: 'BgStub', render: () => h('div') }) }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: defineComponent({ name: 'MmStub', render: () => h('div') }) }))
vi.mock('@vue-flow/controls', () => ({ Controls: defineComponent({ name: 'CtlStub', render: () => h('div') }) }))
vi.mock('@ant-design/icons-vue', () => ({
  FullscreenOutlined: defineComponent({ name: 'FsEnter', render: () => h('i') }),
  FullscreenExitOutlined: defineComponent({ name: 'FsExit', render: () => h('i') }),
}))

import GraphWorkbenchPage from '../GraphWorkbenchPage.vue'

const studioFixture = {
  nodes: [
    { id: 'n1', label: 'Alpha', type: 'concept' },
    { id: 'n2', label: 'Beta', type: 'concept' },
    { id: 'n3', label: 'Gamma', type: 'concept' },
  ],
  edges: [
    { source: 'n1', target: 'n2', relation: 'rel' },
    { source: 'n2', target: 'n3', relation: 'rel' },
  ],
  total_nodes: 3,
  truncated: false,
  tenant_scoped: false,
  schema: { terms: [], rules: [], schema_version: 1 },
}

/** 超出 LAYOUT_NODE_BUDGET(500) 的节点集（501 个星型全连通——默认枢纽邻域
 *  视图把无边节点滤空，必须让全部节点落在 2 跳内才会进布局降级路径）。 */
function oversizedFixture() {
  const nodes = Array.from({ length: 501 }, (_, i) => ({ id: `n${i}`, label: `N${i}`, type: 'concept' }))
  const edges = nodes.slice(1).map((n) => ({ source: 'n0', target: n.id, relation: 'rel' }))
  return { ...studioFixture, nodes, edges, total_nodes: nodes.length }
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      ontology: {
        layoutDegradedHint: '布局降级：{count} 节点超预算 {budget}',
        nodeBudgetWarning: '节点超限',
      },
      knowledge: { workbenchTitle: '图谱工作台' },
      canvas: { fullscreenEnter: '全屏', fullscreenExit: '退出' },
      common: { refresh: '刷新', error: '操作失败', noData: '暂无数据' },
    },
  },
})

const passthrough = { template: '<div class="ant-stub"><slot /></div>' }
const antStubs = Object.fromEntries(
  ['a-tag', 'a-radio-group', 'a-radio-button', 'a-alert', 'a-spin', 'a-input-search',
    'a-checkbox', 'a-tabs', 'a-tab-pane', 'a-input', 'a-select', 'a-select-option',
    'a-textarea', 'a-button', 'a-popconfirm', 'a-empty'].map((name) => [name, passthrough]),
)

async function mountPage(fixture: unknown) {
  requestGet.mockResolvedValue(fixture)
  const wrapper = mount(GraphWorkbenchPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassCard: { template: '<div class="glass-card-stub"><slot /></div>' },
        FlowEdge: true,
        'router-link': { template: '<a><slot /></a>' },
        ...antStubs,
      },
    },
  })
  await flushPromises()
  return wrapper
}

const degradedVisible = (wrapper: ReturnType<typeof mount>) =>
  wrapper.find('[data-testid="layout-degraded-warning"]').exists()

describe('GraphWorkbenchPage — 3.6-3 布局降级警示随数据复位', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('超预算（501 节点）挂载即警示', async () => {
    const wrapper = await mountPage(oversizedFixture())
    expect(degradedVisible(wrapper)).toBe(true)
  })

  it('小图挂载不警示', async () => {
    const wrapper = await mountPage(studioFixture)
    expect(degradedVisible(wrapper)).toBe(false)
  })

  it('警示可复位：超预算→数据回落小图，警示消失（旧实现只置位不复位）', async () => {
    const wrapper = await mountPage(oversizedFixture())
    expect(degradedVisible(wrapper)).toBe(true)
    const vm = wrapper.vm as any
    vm.studio = studioFixture
    await nextTick()
    await flushPromises()
    expect(degradedVisible(wrapper)).toBe(false)
  })
})
