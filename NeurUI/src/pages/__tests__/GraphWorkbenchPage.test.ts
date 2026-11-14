/**
 * GraphWorkbenchPage — 全屏模式（2D/3D）＋2D 保存拖拽布局 契约测试。
 *
 * 契约面（用户请求：图谱 2D/3D 增加全屏；2D 可保存用户拖拽排列的节点布局）：
 * - 全屏：toolbar 有切换按钮（复用 canvas.fullscreen* 文案），点击对 canvas-stage
 *   请求全屏；fullscreenchange 后 aria-pressed 翻转；再点退出；不支持时禁用。
 * - 保存布局：node-drag-stop 捕获拖拽落点 → 「保存布局」把当前解析位置写入
 *   localStorage（nr-graph-layout:<agentId>）＋success；刷新挂载后该位置盖过放射布局。
 * - 重置布局：清空存储＋拖拽覆盖，回到放射布局（保存可逆）。
 *
 * 重依赖（VueFlow/3D/图标/antd）以桩隔离；红须落在行为断言（按钮缺失／存储未写），
 * 非 import/collection error。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, h, ref, nextTick } from 'vue'

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
  // P2-21：页面取数收口到 api/modules/knowledge-graph 等（内部走 default api 门面）
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
      setup() {
        return () => h('div', { class: 'vue-flow-stub' })
      },
    }),
  }
})
vi.mock('@vue-flow/background', () => ({ Background: defineComponent({ name: 'BgStub', render: () => h('div') }) }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: defineComponent({ name: 'MmStub', render: () => h('div') }) }))
vi.mock('@vue-flow/controls', () => ({ Controls: defineComponent({ name: 'CtlStub', render: () => h('div') }) }))
vi.mock('@ant-design/icons-vue', () => ({
  FullscreenOutlined: defineComponent({ name: 'FsEnter', render: () => h('i', { class: 'fs-enter' }) }),
  FullscreenExitOutlined: defineComponent({ name: 'FsExit', render: () => h('i', { class: 'fs-exit' }) }),
}))

import GraphWorkbenchPage from '@/pages/GraphWorkbenchPage.vue'
import { VueFlow } from '@vue-flow/core'
import { message } from 'ant-design-vue'

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

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        workbenchTitle: '图谱工作台',
        workbenchSaveLayout: '保存布局',
        workbenchLayoutSaved: '布局已保存',
        workbenchResetLayout: '重置布局',
        workbenchLayoutReset: '布局已重置',
      },
      canvas: {
        fullscreenEnter: '画布全屏',
        fullscreenExit: '退出全屏 (Esc)',
        fullscreenUnsupported: '当前浏览器不支持全屏',
      },
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

const LAYOUT_KEY = 'nr-graph-layout:agent-1'

async function mountPage(fixture = studioFixture) {
  requestGet.mockResolvedValue(fixture)
  const wrapper = mount(GraphWorkbenchPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassCard: { template: '<div class="glass-card-stub"><slot /></div>' },
        FlowEdge: true,
        'router-link': { template: '<a class="router-link-stub"><slot /></a>' },
        ...antStubs,
      },
    },
  })
  await flushPromises()
  return wrapper
}

function flowNodesOf(wrapper: ReturnType<typeof mount>) {
  const flow = wrapper.findComponent(VueFlow)
  return (flow.props('nodes') ?? []) as Array<{ id: string; position: { x: number; y: number } }>
}

function flowEdgesOf(wrapper: ReturnType<typeof mount>) {
  const flow = wrapper.findComponent(VueFlow)
  return (flow.props('edges') ?? []) as Array<{ id: string; source: string; target: string }>
}

describe('GraphWorkbenchPage 全屏模式', () => {
  let requestFullscreenSpy: ReturnType<typeof vi.fn>
  let exitFullscreenSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    requestFullscreenSpy = vi.fn()
    exitFullscreenSpy = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', {
      value: requestFullscreenSpy, configurable: true, writable: true,
    })
    Object.defineProperty(document, 'exitFullscreen', {
      value: exitFullscreenSpy, configurable: true, writable: true,
    })
    Object.defineProperty(document, 'fullscreenElement', {
      value: null, configurable: true, writable: true,
    })
  })

  afterEach(() => {
    document.dispatchEvent(new Event('fullscreenchange'))
  })

  it('toolbar 提供全屏切换按钮，点击对画布舞台请求全屏', async () => {
    const wrapper = await mountPage()
    const btn = wrapper.find('[data-testid="workbench-fullscreen"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(requestFullscreenSpy).toHaveBeenCalledTimes(1)
  })

  it('fullscreenchange 后 aria-pressed 翻转，再点退出全屏', async () => {
    const wrapper = await mountPage()
    const btn = wrapper.find('[data-testid="workbench-fullscreen"]')
    expect(btn.attributes('aria-pressed')).toBe('false')
    await btn.trigger('click')
    const stage = wrapper.find('[data-testid="workbench-canvas-stage"]').element
    Object.defineProperty(document, 'fullscreenElement', { value: stage, configurable: true, writable: true })
    document.dispatchEvent(new Event('fullscreenchange'))
    await nextTick()
    expect(wrapper.find('[data-testid="workbench-fullscreen"]').attributes('aria-pressed')).toBe('true')
    await wrapper.find('[data-testid="workbench-fullscreen"]').trigger('click')
    expect(exitFullscreenSpy).toHaveBeenCalledTimes(1)
  })
})

describe('GraphWorkbenchPage 2D 保存布局', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('拖拽落点经「保存布局」写入 localStorage 并提示成功', async () => {
    const wrapper = await mountPage()
    const flow = wrapper.findComponent(VueFlow)
    flow.vm.$emit('node-drag-stop', { event: {}, node: { id: 'n1', position: { x: 111, y: 222 } }, nodes: [] })
    await nextTick()
    const saveBtn = wrapper.find('[data-testid="workbench-save-layout"]')
    expect(saveBtn.exists()).toBe(true)
    await saveBtn.trigger('click')
    const stored = JSON.parse(localStorage.getItem(LAYOUT_KEY) ?? '{}')
    expect(stored.n1).toEqual({ x: 111, y: 222 })
    expect(message.success).toHaveBeenCalled()
  })

  it('挂载时已存布局盖过放射布局位置', async () => {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ n1: { x: 50, y: 60 } }))
    const wrapper = await mountPage()
    const n1 = flowNodesOf(wrapper).find((n) => n.id === 'n1')
    expect(n1?.position).toEqual({ x: 50, y: 60 })
  })

  it('「重置布局」清空存储与拖拽覆盖', async () => {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ n1: { x: 50, y: 60 } }))
    const wrapper = await mountPage()
    const resetBtn = wrapper.find('[data-testid="workbench-reset-layout"]')
    expect(resetBtn.exists()).toBe(true)
    await resetBtn.trigger('click')
    expect(localStorage.getItem(LAYOUT_KEY)).toBeNull()
    const n1 = flowNodesOf(wrapper).find((n) => n.id === 'n1')
    expect(n1?.position).not.toEqual({ x: 50, y: 60 })
  })
})

describe('GraphWorkbenchPage 2D 边渲染集契约', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  // 根因钉子（用户报障：全图态刷新后关系线显示不全，切 3D 回 2D 才全）：
  // vue-flow 挂载时丢弃端点未注册的边，且节点后续加入不回扫——端点悬空的边
  // 留在 props 里就是丢边隐患。契约：传给画布的边必须是节点集的导出子图。
  it('端点不在节点渲染集的边不得进入画布 props', async () => {
    const fixture = {
      ...studioFixture,
      edges: [
        ...studioFixture.edges,
        { source: 'n2', target: 'ghost', relation: 'dangling' },
      ],
    }
    const wrapper = await mountPage(fixture)
    const nodeIds = new Set(flowNodesOf(wrapper).map((n) => n.id))
    expect(nodeIds.has('ghost')).toBe(false)
    for (const e of flowEdgesOf(wrapper)) {
      expect(nodeIds.has(e.source), `边 ${e.id}(${e.source}->${e.target}) 端点不在节点集`).toBe(true)
      expect(nodeIds.has(e.target), `边 ${e.id}(${e.source}->${e.target}) 端点不在节点集`).toBe(true)
    }
  })

  it('两端都在渲染集内的边全部保留（不过度过滤）', async () => {
    const wrapper = await mountPage()
    const edges = flowEdgesOf(wrapper)
    expect(edges.map((e) => `${e.source}->${e.target}`).sort()).toEqual(['n1->n2', 'n2->n3'])
  })
})