/**
 * SwarmFlowPanel 桩测试（P1-1）：给固定投影 JSON，断言节点/边渲染数量、
 * 状态着色与边标注；truncated/incomplete 诚实提示可见；空投影出空态。
 * VueFlow 以桩隔离（GraphWorkbenchPage.test.ts 同款），红须落在行为断言。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import type { SwarmGraphNode, SwarmGraphResult } from '@/types/swarmGraph'

vi.mock('@vue-flow/core', async () => {
  const { defineComponent, h } = await import('vue')
  const VueFlow = defineComponent({
    name: 'VueFlowStub',
    props: ['nodes', 'edges'],
    setup(props, { slots }) {
      return () =>
        h(
          'div',
          { class: 'vue-flow-stub' },
          (props.nodes ?? []).map((n: any) =>
            h(
              'div',
              { class: 'stub-node', 'data-id': n.id },
              slots['node-swarm'] ? slots['node-swarm']({ data: n.data, position: n.position }) : n.id,
            ),
          ),
        )
    },
  })
  const Handle = defineComponent({ name: 'HandleStub', setup: () => () => null })
  return {
    VueFlow,
    Handle,
    Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  }
})
vi.mock('@vue-flow/background', () => ({ Background: { name: 'BackgroundStub', render: () => null } }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: { name: 'MiniMapStub', render: () => null } }))
vi.mock('@vue-flow/controls', () => ({ Controls: { name: 'ControlsStub', render: () => null } }))

import SwarmFlowPanel from '../SwarmFlowPanel.vue'

const messages = {
  'zh-CN': {
    swarmFlow: {
      title: '协作拓扑',
      summary: '{runs} 个成员 · {edges} 条关系 · 集成版本 {revision}',
      truncatedHint: '子任务数超上限，仅显示最近 {count} 个',
      incompleteHint: '候选事件账本不完整，图形仅含可重放部分',
      legendSpawn: '委派',
      legendDependency: '依赖',
      legendApproval: '审批',
      legendCandidate: '候选',
      edgeApproval: '审批 {level} · {verdict}',
      edgeCandidate: '候选 · {status}',
      verdictApproved: '已批准',
      verdictRejected: '已否决',
      verdictPending: '待裁决',
      externalBadge: '外部',
      depthBadge: 'D{depth}',
      emptyHint: '该会话暂无子任务运行',
    },
  },
}

function runNode(id: string, overrides: Partial<SwarmGraphNode> = {}): SwarmGraphNode {
  const base: SwarmGraphNode = {
    id,
    nodeType: 'run',
    run_id: `run-${id}`,
    member_name: id,
    kind: 'internal',
    executor_tool: '',
    status: 'completed',
    depth: 1,
    team_id: 't1',
    started_at: 1000,
    finished_at: 1100,
    duration_ms: 100000,
    error_type: '',
    level: '',
    decision: '',
    decided_by: '',
    request_id: '',
    candidate_id: '',
    artifact_keys: [],
    base_revision: 0,
    note: '',
  }
  return { ...base, ...overrides }
}

const projection: SwarmGraphResult = {
  parent_session_id: 'sess-1',
  nodes: [
    runNode('swarm-a'),
    runNode('swarm-b', { status: 'running', depth: 2, kind: 'external', executor_tool: 'claude-code' }),
    runNode('swarm-c', { status: 'failed', error_type: 'acceptance_failed' }),
    {
      ...runNode('swarm-a'),
      id: 'approval:req-1',
      nodeType: 'approval',
      run_id: 'swarm-a',
      member_name: 'merge_candidate:cand-x',
      status: 'approved',
      level: 'L1',
      decision: 'approve',
      decided_by: 'u1',
      request_id: 'req-1',
    },
    {
      ...runNode('swarm-b'),
      id: 'candidate:cand-1',
      nodeType: 'candidate',
      run_id: 'swarm-b',
      member_name: 'k1',
      status: 'submitted',
      artifact_keys: ['k1'],
      base_revision: 1,
      candidate_id: 'cand-1',
    },
  ],
  edges: [
    { id: 'spawn:swarm-a->swarm-b', type: 'spawn', from: 'swarm-a', to: 'swarm-b' },
    { id: 'dep:swarm-a->swarm-c', type: 'dependency', from: 'swarm-a', to: 'swarm-c' },
    { id: 'approval:req-1', type: 'approval', from: 'swarm-a', to: 'approval:req-1', level: 'L1', status: 'approved', decision: 'approve', decided_by: 'u1' },
    { id: 'candidate:cand-1', type: 'candidate', from: 'swarm-b', to: 'candidate:cand-1', status: 'submitted' },
  ],
  meta: {
    revision: 2,
    generated_at: 1,
    truncated: false,
    candidates_incomplete: false,
    counts: { nodes: 5, edges: 4 },
  },
}

const stubs = {
  GlassCard: { props: [], template: '<div class="gc"><slot /></div>' },
  'a-alert': { props: ['message', 'type'], template: '<div class="stub-alert">{{ message }}</div>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
}

function mountPanel(projectionProp: SwarmGraphResult | null, loading = false) {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(SwarmFlowPanel, {
    props: { projection: projectionProp, loading },
    global: { plugins: [i18n], stubs },
  })
}

describe('SwarmFlowPanel', () => {
  it('投影 → 节点/边全量渲染（v2 四类边都在）', () => {
    const w = mountPanel(projection)
    const stub = w.find('.vue-flow-stub')
    expect(stub.exists()).toBe(true)
    expect(w.findAll('.stub-node')).toHaveLength(5)
    const vm: any = w.findComponent({ name: 'VueFlowStub' })
    const edges = vm.props('edges')
    expect(edges).toHaveLength(4)
    const dep = edges.find((e: any) => e.id === 'dep:swarm-a->swarm-c')
    expect(dep.label).toBe('依赖')
    expect(dep.style.strokeDasharray).toBeTruthy()
    const spawn = edges.find((e: any) => e.id === 'spawn:swarm-a->swarm-b')
    expect(spawn.class).toContain('nf-edge-spawn')
    const approval = edges.find((e: any) => e.id === 'approval:req-1')
    expect(approval.label).toBe('审批 L1 · 已批准')
    const candidate = edges.find((e: any) => e.id === 'candidate:cand-1')
    expect(candidate.label).toBe('候选 · submitted')
  })

  it('节点按状态着色 + 外部成员徽标 + 卡片形态', () => {
    const w = mountPanel(projection)
    const failedNode = w.find('[data-id="swarm-c"] .nf-node')
    expect(failedNode.classes()).toContain('nf-tone-failed')
    const runningNode = w.find('[data-id="swarm-b"] .nf-node')
    expect(runningNode.classes()).toContain('nf-tone-running')
    expect(runningNode.text()).toContain('外部')
    const approvalCard = w.find('[data-id="approval:req-1"] .nf-node')
    expect(approvalCard.classes()).toContain('nf-node-card')
    expect(approvalCard.text()).toContain('L1')
    const candidateCard = w.find('[data-id="candidate:cand-1"] .nf-node')
    expect(candidateCard.text()).toContain('submitted')
  })

  it('meta 诚实标注可见（truncated / candidates_incomplete）', () => {
    const w = mountPanel({
      ...projection,
      meta: { ...projection.meta, truncated: true, candidates_incomplete: true },
    })
    const hints = w.findAll('.stub-alert').map(a => a.text())
    expect(hints.some(t => t.includes('仅显示最近 3 个'))).toBe(true)
    expect(hints.some(t => t.includes('不完整'))).toBe(true)
  })

  it('空投影 → 空态；null 投影 + loading → 不出空态', () => {
    const empty = mountPanel({
      ...projection,
      nodes: [],
      edges: [],
    })
    expect(empty.find('.stub-empty').exists()).toBe(true)
    const loading = mountPanel(null, true)
    expect(loading.find('.stub-empty').exists()).toBe(false)
  })
})
