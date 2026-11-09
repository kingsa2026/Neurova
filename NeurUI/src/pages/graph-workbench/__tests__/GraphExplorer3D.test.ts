/**
 * GraphExplorer3D — 画布撑满＋全节点入视 契约测试。
 *
 * 缺陷面（用户实测两症）：
 *  1. 全屏后只有上半屏是画布：`.explorer3d-canvas` 无 flex:1/显式高，高度靠库内联
 *     内容撑，父级在全屏长高后它不跟随 ⇒ 下半屏空。尺寸属 CSS 布局，jsdom 无排版
 *     引擎量不到，落浏览器活体；本档钉与之联动的行为面——resize 必须重测量容器。
 *  2. 没有展示全部节点：相机固定 z:320、无 zoomToFit，力导布局铺开后的包围盒超出
 *     视口 ⇒ 节点细小且边缘被裁。行为判据＝数据到位引擎冷却后必须 zoomToFit，
 *     且 resize（全屏切换会派发）后必须重新 fit。
 *  3. 点画布空白＝刷新图谱：onBackgroundClick 无条件 resetToFull→refetch，全图态
 *     点空白也重拉整图；且经 prop 聚焦时退出请求读到陈旧 focusId，连「回到全图」
 *     都退不出去。行为判据＝全图态点空白零请求；聚焦视图退出请求不带 focus。
 *
 * 重依赖（3d-force-graph/three/WebGL）以桩隔离；红须落在行为断言（zoomToFit 零调用），
 * 非 import/collection error。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const { graphState } = vi.hoisted(() => ({
  graphState: { instances: [] as any[] },
}))

vi.mock('3d-force-graph', () => {
  const chainOnly = [
    'backgroundColor', 'nodeThreeObjectExtend', 'nodeLabel',
    'linkColor', 'linkWidth', 'linkOpacity', 'linkCurvature',
    'linkDirectionalParticles', 'linkDirectionalParticleSpeed',
    'linkDirectionalParticleWidth', 'linkDirectionalParticleColor', 'lights',
  ]
  class ForceGraph3D {
    el: any
    calls: Record<string, any[]>
    _nodeThreeObjectCb: any
    _onEngineStopCb: any
    _onNodeClickCb: any
    _onBackgroundClickCb: any
    constructor(el: any) {
      this.el = el
      this.calls = {
        width: [], height: [], zoomToFit: [], graphData: [], cameraPosition: [],
      }
      for (const m of chainOnly) (this as any)[m] = () => this
      ;(this as any).nodeThreeObject = (cb?: any) => {
        if (cb === undefined) return this._nodeThreeObjectCb
        this._nodeThreeObjectCb = cb
        return this
      }
      ;(this as any).onEngineStop = (cb: any) => { this._onEngineStopCb = cb; return this }
      ;(this as any).onNodeClick = (cb?: any) => {
        if (cb === undefined) return this._onNodeClickCb
        this._onNodeClickCb = cb
        return this
      }
      ;(this as any).onBackgroundClick = (cb?: any) => {
        if (cb === undefined) return this._onBackgroundClickCb
        this._onBackgroundClickCb = cb
        return this
      }
      ;(this as any).width = (v: number) => { this.calls.width.push(v); return this }
      ;(this as any).height = (v: number) => { this.calls.height.push(v); return this }
      ;(this as any).graphData = (d: any) => { this.calls.graphData.push(d); return this }
      ;(this as any).cameraPosition = (p: any) => { this.calls.cameraPosition.push(p); return this }
      ;(this as any).zoomToFit = (...args: any[]) => { this.calls.zoomToFit.push(args); return this }
      ;(this as any)._destructor = () => {}
      graphState.instances.push(this)
    }
  }
  return { default: ForceGraph3D }
})

vi.mock('three', () => {
  class Light { constructor(..._args: any[]) {} }
  return {
    Group: class { add() {} },
    SphereGeometry: class {},
    MeshStandardMaterial: class {},
    MeshBasicMaterial: class {},
    Mesh: class {},
    SpriteMaterial: class {},
    Sprite: class { scale = { set() {} }; position = { set() {} } },
    CanvasTexture: class { needsUpdate = false },
    AmbientLight: Light,
    DirectionalLight: Light,
    PointLight: Light,
    BackSide: 1,
  }
})

const { requestGet } = vi.hoisted(() => ({ requestGet: vi.fn() }))
vi.mock('@/api', () => ({
  request: { get: requestGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import GraphExplorer3D from '@/pages/graph-workbench/GraphExplorer3D.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        workbenchFocus: '焦点节点 ID', workbenchHops: '跳数',
        workbenchFullGraph: '回到全图', workbenchFilterTypes: '类型',
        workbenchTruncatedHint: '共 {total} 节点',
      },
      common: { refresh: '刷新', error: '操作失败', noData: '暂无数据' },
    },
  },
})

const passthrough = { template: '<div class="ant-stub"><slot /></div>' }
const antStubs = Object.fromEntries(
  ['a-input', 'a-select', 'a-select-option', 'a-tag', 'a-empty']
    .map((name) => [name, passthrough]),
)

const subgraphFixture = {
  nodes: [
    { id: 'n1', label: 'Alpha', type: 'concept' },
    { id: 'n2', label: 'Beta', type: 'person' },
    { id: 'n3', label: 'Gamma', type: 'concept' },
  ],
  edges: [
    { source: 'n1', target: 'n2', relation: 'rel' },
    { source: 'n2', target: 'n3', relation: 'rel' },
  ],
  total_nodes: 3,
  truncated: false,
}

async function mountExplorer(
  fixture: any = subgraphFixture,
  extraProps: Record<string, unknown> = {},
) {
  requestGet.mockResolvedValue(fixture)
  const wrapper = mount(GraphExplorer3D, {
    props: { agentId: 'agent-1', ...extraProps },
    global: {
      plugins: [i18n],
      stubs: {
        GlassButton: { template: '<button class="glass-btn-stub"><slot /></button>' },
        ...antStubs,
      },
    },
  })
  await flushPromises()
  return wrapper
}

function lastGraph() {
  return graphState.instances[graphState.instances.length - 1]
}

function stubContainerSize(wrapper: ReturnType<typeof mount>, w: number, h: number) {
  const el = wrapper.find('.explorer3d-canvas').element as HTMLElement
  Object.defineProperty(el, 'clientWidth', { value: w, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: h, configurable: true })
  return el
}

describe('GraphExplorer3D 全节点入视', () => {
  beforeEach(() => {
    graphState.instances.length = 0
    vi.clearAllMocks()
  })

  it('数据到位、力导引擎冷却后 zoomToFit 把全部节点框入视口', async () => {
    await mountExplorer()
    const g = lastGraph()
    expect(g).toBeTruthy()
    expect(g.calls.graphData.length).toBeGreaterThan(0)
    expect(g.calls.graphData[0].nodes).toHaveLength(3)
    // 引擎冷却回调触发后才 fit（布局 settled 的包围盒才真实）
    g._onEngineStopCb?.()
    expect(
      g.calls.zoomToFit.length,
      '引擎冷却后必须 zoomToFit，否则固定相机距离裁掉边缘节点（用户症 2）',
    ).toBeGreaterThan(0)
  })

  it('空数据不触发 fit（无节点可框）', async () => {
    await mountExplorer({ nodes: [], edges: [], total_nodes: 0, truncated: false })
    const g = lastGraph()
    g._onEngineStopCb?.()
    expect(g.calls.zoomToFit.length).toBe(0)
  })
})

describe('GraphExplorer3D resize 重测量＋重 fit', () => {
  beforeEach(() => {
    graphState.instances.length = 0
    vi.clearAllMocks()
  })

  it('resize 按容器真实尺寸重设宽高并重新 fit（全屏切换派发的 resize 同路）', async () => {
    const wrapper = await mountExplorer()
    const g = lastGraph()
    stubContainerSize(wrapper, 1200, 900)
    g.calls.width.length = 0
    g.calls.height.length = 0
    g.calls.zoomToFit.length = 0
    window.dispatchEvent(new Event('resize'))
    expect(g.calls.width).toContain(1200)
    expect(g.calls.height).toContain(900)
    expect(
      g.calls.zoomToFit.length,
      'resize 改变视口后必须重新 fit，否则全屏长高的画布仍按旧包围盒裁节点',
    ).toBeGreaterThan(0)
  })
})

describe('GraphExplorer3D 渲染上限单源', () => {
  beforeEach(() => {
    graphState.instances.length = 0
    vi.clearAllMocks()
  })

  it('subgraph 请求不再自带第二份 limit（缺省跟全局设置，由服务端解析）', async () => {
    await mountExplorer()
    expect(requestGet).toHaveBeenCalledWith(
      '/knowledge-graph/agent-1/subgraph',
      { params: { hops: 2 } },
    )
  })
})

describe('GraphExplorer3D 画布空白点击', () => {
  beforeEach(() => {
    graphState.instances.length = 0
    vi.clearAllMocks()
  })

  it('全图态点空白不发请求（此前点空白＝重拉整图，用户实测 bug）', async () => {
    await mountExplorer()
    expect(requestGet).toHaveBeenCalledTimes(1)
    lastGraph()._onBackgroundClickCb?.()
    await flushPromises()
    expect(
      requestGet,
      '全图态没有焦点可退，点空白发第二次请求就是把画布点击变成刷新',
    ).toHaveBeenCalledTimes(1)
  })

  it('聚焦视图点空白真正退回全图：退出请求不带 focus（prop 陈旧曾致退不出去）', async () => {
    await mountExplorer(subgraphFixture, { focusId: 'n2' })
    // 进入请求带 focus（prop 聚焦视图）
    expect(requestGet).toHaveBeenLastCalledWith(
      '/knowledge-graph/agent-1/subgraph',
      { params: { hops: 2, focus: 'n2' } },
    )
    lastGraph()._onBackgroundClickCb?.()
    await flushPromises()
    // 退出请求必须不带 focus：emit('clear') 后父级 prop 同步晚于本次请求，
    // 退出请求若读 props.focusId 会把原聚焦视图原样拉回来（回到全图按钮同一根因）。
    expect(requestGet).toHaveBeenLastCalledWith(
      '/knowledge-graph/agent-1/subgraph',
      { params: { hops: 2 } },
    )
  })

  it('全图态点节点再点空白：清高亮并通知父级，但不发请求', async () => {
    const wrapper = await mountExplorer()
    const g = lastGraph()
    g._onNodeClickCb?.({ id: 'n1', name: 'Alpha' })
    g._onBackgroundClickCb?.()
    await flushPromises()
    expect(wrapper.emitted('clear')).toBeTruthy()
    expect(
      requestGet,
      '取消高亮不是换数据：清选中不得触发 refetch',
    ).toHaveBeenCalledTimes(1)
  })
})