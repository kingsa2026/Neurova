<template>
  <GlassCard class="swarm-flow-panel" data-testid="swarm-flow-panel">
    <div class="swarm-flow-head">
      <span class="swarm-flow-title" data-testid="swarm-flow-title">{{ t('swarmFlow.title') }}</span>
      <span v-if="summaryText" class="swarm-flow-summary" data-testid="swarm-flow-summary">{{ summaryText }}</span>
    </div>

    <!-- 诚实标注：截断 / 候选账本缺事件（P2-4 meta 契约） -->
    <a-alert
      v-if="projection?.meta?.truncated"
      type="warning"
      show-icon
      class="swarm-flow-hint"
      :message="t('swarmFlow.truncatedHint', { count: runNodeCount })"
    />
    <a-alert
      v-if="projection?.meta?.candidates_incomplete"
      type="info"
      show-icon
      class="swarm-flow-hint"
      :message="t('swarmFlow.incompleteHint')"
    />

    <div class="swarm-flow-legend" data-testid="swarm-flow-legend">
      <span class="legend-item"><span class="legend-line legend-spawn" />{{ t('swarmFlow.legendSpawn') }}</span>
      <span class="legend-item"><span class="legend-line legend-dep" />{{ t('swarmFlow.legendDependency') }}</span>
      <span class="legend-item"><span class="legend-line legend-approval" />{{ t('swarmFlow.legendApproval') }}</span>
      <span class="legend-item"><span class="legend-line legend-candidate" />{{ t('swarmFlow.legendCandidate') }}</span>
    </div>

    <div class="swarm-flow-wrap">
      <VueFlow
        v-if="flowNodes.length"
        :nodes="flowNodes"
        :edges="flowEdges"
        :fit-view-on-init="true"
        :min-zoom="0.2"
        :max-zoom="2"
        class="swarm-flow"
      >
        <Background />
        <MiniMap pannable zoomable />
        <Controls />
        <template #node-swarm="nodeProps">
          <div class="nf-node" :class="nodeToneClass(nodeProps.data)" :data-node-type="nodeProps.data.nodeType">
            <template v-if="nodeProps.data.nodeType === 'run'">
              <div class="nf-node-title">
                <span class="nf-node-name">{{ nodeProps.data.member_name }}</span>
                <span v-if="nodeProps.data.kind === 'external'" class="nf-badge">
                  {{ t('swarmFlow.externalBadge') }}
                </span>
              </div>
              <div class="nf-node-sub">
                <span class="nf-node-status">{{ nodeProps.data.status }}</span>
                <span class="nf-node-depth">{{ t('swarmFlow.depthBadge', { depth: nodeProps.data.depth }) }}</span>
              </div>
            </template>
            <template v-else-if="nodeProps.data.nodeType === 'approval'">
              <div class="nf-node-title">
                <span class="nf-node-kind">{{ t('swarmFlow.legendApproval') }}</span>
                <span class="nf-node-level">{{ nodeProps.data.level }}</span>
              </div>
              <div class="nf-node-sub">
                <span>{{ nodeProps.data.decision || nodeProps.data.status }}</span>
              </div>
            </template>
            <template v-else>
              <div class="nf-node-title">
                <span class="nf-node-kind">{{ t('swarmFlow.legendCandidate') }}</span>
                <span class="nf-node-status">{{ nodeProps.data.status }}</span>
              </div>
              <div class="nf-node-sub">
                <span>{{ nodeProps.data.member_name }}</span>
              </div>
            </template>
          </div>
          <Handle type="target" :position="Position.Left" />
          <Handle type="source" :position="Position.Right" />
        </template>
      </VueFlow>
      <a-empty v-else-if="!loading" :description="t('swarmFlow.emptyHint')" />
    </div>
  </GlassCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { VueFlow, Handle, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/minimap/dist/style.css'
import '@vue-flow/controls/dist/style.css'
import GlassCard from '@/components/GlassCard.vue'
import type {
  SwarmGraphEdge,
  SwarmGraphNode,
  SwarmGraphResult,
} from '@/types/swarmGraph'

/**
 * 蜂群协作拓扑图面板（P1-1，拍板 D-A：v2 全边集）。
 *
 * 纯渲染组件（P2-4 契约）：只吃服务端投影 props（SwarmGraphResult），
 * 不 import 事件语义、不做 trace 解释；节点/边的语义着色映射是本组件内
 * 仅有的"词汇翻译"，且键集被 tests/unit/api/test_swarm_graph_contract.py
 * 钉在台账/蜂群/候选状态词汇内（LEDGER_TO_WINDOW_STATUS 对齐先例）。
 * 增量刷新由接线点（ChatPage）经既有 useSessionSync 事件触发重取投影。
 */
const props = defineProps<{
  projection: SwarmGraphResult | null
  loading?: boolean
}>()

const { t } = useI18n()

/** 台账/蜂群 run 状态 → 着色基调（键集钉在后台状态词汇内，契约测试守护）。 */
const RUN_STATUS_TONE: Record<string, string> = {
  queued: 'running',
  pending: 'running',
  parked: 'running',
  running: 'running',
  in_review: 'running',
  completed: 'completed',
  failed: 'failed',
  cancelled: 'failed',
}

/** 候选状态 → 着色基调（键集=候选状态域四值）。 */
const CANDIDATE_STATUS_TONE: Record<string, string> = {
  submitted: 'running',
  accepted: 'completed',
  rejected: 'failed',
  reviseRequired: 'warning',
}

/** 审批裁决态 → 着色基调。 */
const APPROVAL_TONE: Record<string, string> = {
  approved: 'completed',
  rejected: 'failed',
  pending: 'running',
}

function runTone(status: string): string {
  return RUN_STATUS_TONE[status] ?? 'running'
}

function nodeToneClass(node: SwarmGraphNode): string {
  if (node.nodeType === 'approval') {
    return `nf-tone-${APPROVAL_TONE[node.status] ?? 'running'} nf-node-card`
  }
  if (node.nodeType === 'candidate') {
    return `nf-tone-${CANDIDATE_STATUS_TONE[node.status] ?? 'running'} nf-node-card`
  }
  return `nf-tone-${runTone(node.status)}`
}

/** 分层布局：run 节点按 depth 横向分层、同层纵向堆叠；卡节点挂源 run 右侧。 */
function layout(nodes: SwarmGraphNode[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>()
  const perDepth = new Map<number, number>()
  for (const node of nodes) {
    if (node.nodeType !== 'run') continue
    const depth = node.depth || 1
    const idx = perDepth.get(depth) ?? 0
    perDepth.set(depth, idx + 1)
    pos.set(node.id, { x: depth * 280, y: idx * 116 })
  }
  for (const node of nodes) {
    if (node.nodeType === 'run') continue
    const base = pos.get(node.run_id) ?? { x: 0, y: 0 }
    const col = node.nodeType === 'approval' ? 1 : 2
    pos.set(node.id, { x: base.x + col * 210, y: base.y + (col - 1) * 52 })
  }
  return pos
}

const flowNodes = computed(() => {
  const nodes = props.projection?.nodes ?? []
  const pos = layout(nodes)
  return nodes.map(node => ({
    id: node.id,
    type: 'swarm',
    position: pos.get(node.id) ?? { x: 0, y: 0 },
    data: { ...node },
  }))
})

function approvalLabel(edge: SwarmGraphEdge): string {
  return t('swarmFlow.edgeApproval', {
    level: edge.level || '-',
    verdict: t(`swarmFlow.verdict${(edge.status || 'pending').charAt(0).toUpperCase()}${(edge.status || 'pending').slice(1)}`),
  })
}

function isActiveRun(targetId: string): boolean {
  const node = (props.projection?.nodes ?? []).find(n => n.id === targetId)
  return !!node && runTone(node.status) === 'running'
}

const flowEdges = computed(() =>
  (props.projection?.edges ?? []).map(edge => {
    const base = { id: edge.id, source: edge.from, target: edge.to }
    if (edge.type === 'dependency') {
      return {
        ...base,
        label: t('swarmFlow.legendDependency'),
        class: 'nf-edge nf-edge-dep',
        style: { strokeDasharray: '6 4' },
      }
    }
    if (edge.type === 'approval') {
      return {
        ...base,
        label: approvalLabel(edge),
        class: `nf-edge nf-edge-approval nf-tone-${APPROVAL_TONE[edge.status ?? 'pending'] ?? 'running'}`,
      }
    }
    if (edge.type === 'candidate') {
      return {
        ...base,
        label: t('swarmFlow.edgeCandidate', { status: edge.status ?? '' }),
        class: `nf-edge nf-edge-candidate nf-tone-${CANDIDATE_STATUS_TONE[edge.status ?? ''] ?? 'running'}`,
      }
    }
    return {
      ...base,
      class: 'nf-edge nf-edge-spawn',
      animated: isActiveRun(edge.to),
    }
  }),
)

const runNodeCount = computed(
  () => (props.projection?.nodes ?? []).filter(n => n.nodeType === 'run').length,
)

const summaryText = computed(() => {
  const meta = props.projection?.meta
  if (!meta) return ''
  const counts = meta.counts ?? {}
  return t('swarmFlow.summary', {
    runs: runNodeCount.value,
    edges: counts.edges ?? (props.projection?.edges ?? []).length,
    revision: meta.revision ?? 0,
  })
})
</script>

<style scoped>
.swarm-flow-panel { display: flex; flex-direction: column; gap: 8px; }
.swarm-flow-head { display: flex; align-items: baseline; gap: 12px; }
.swarm-flow-title { font-weight: 600; font-size: 14px; color: var(--nr-text-primary); }
.swarm-flow-summary { font-size: 12px; color: var(--nr-text-secondary); }
.swarm-flow-hint { margin: 0; }
.swarm-flow-legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--nr-text-secondary); }
.legend-item { display: inline-flex; align-items: center; gap: 6px; }
.legend-line { display: inline-block; width: 22px; height: 0; border-top: 2px solid var(--nr-primary); }
.legend-dep { border-top-style: dashed; border-color: var(--nr-text-secondary); }
.legend-approval { border-color: var(--nr-warning); }
.legend-candidate { border-color: var(--nr-primary-light); }
.swarm-flow-wrap { height: 300px; border: 1px solid var(--nr-glass-border); border-radius: 10px; overflow: hidden; background: var(--nr-bg-inset); }
.swarm-flow { width: 100%; height: 100%; }

/* 节点形态：状态着色全部走语义令牌，不硬编码色值（themes 契约） */
.nf-node {
  min-width: 150px; padding: 8px 10px; border-radius: 10px;
  border: 1px solid var(--nr-glass-border); background: var(--nr-bg-elevated);
  color: var(--nr-text-primary); font-size: 12px;
}
.nf-node-title { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.nf-node-sub { display: flex; gap: 8px; margin-top: 4px; color: var(--nr-text-secondary); }
.nf-node-name { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nf-badge { font-size: 10px; padding: 0 6px; border-radius: 8px; border: 1px solid var(--nr-primary-soft-border); color: var(--nr-primary-light); }
.nf-node.nf-tone-running { border-color: var(--nr-warning-soft-border); }
.nf-node.nf-tone-completed { border-color: var(--nr-success-soft-border); }
.nf-node.nf-tone-failed { border-color: var(--nr-error-soft-border); }
.nf-node.nf-tone-warning { border-color: var(--nr-warning-soft-border); }
.nf-node-card { background: var(--nr-bg-surface); }

/* 边着色：spawn 实线（运行中流动）、dependency 虚线、approval/candidate 带标注 */
.swarm-flow :deep(.nf-edge-spawn path) { stroke: var(--nr-primary); }
.swarm-flow :deep(.nf-edge-dep path) { stroke: var(--nr-text-secondary); }
.swarm-flow :deep(.nf-edge-approval path) { stroke: var(--nr-warning); }
.swarm-flow :deep(.nf-edge-candidate path) { stroke: var(--nr-primary-light); }
.swarm-flow :deep(.nf-edge.nf-tone-failed path) { stroke: var(--nr-error); }
.swarm-flow :deep(.nf-edge.nf-tone-completed path) { stroke: var(--nr-success); }
</style>
