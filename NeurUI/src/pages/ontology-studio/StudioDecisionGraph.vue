<template>
  <div class="decision-graph" data-testid="studio-decision-graph">
    <div class="view-head">
      <h4 class="view-title">{{ t('ontology.decisionGraphTitle') }}</h4>
      <GlassButton
        size="sm"
        variant="secondary"
        :loading="loading"
        data-testid="decision-graph-refresh"
        @click="reload"
      >
        {{ t('ontology.decisionGraphRefresh') }}
      </GlassButton>
    </div>

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      data-testid="decision-graph-error"
      :message="t('ontology.decisionGraphLoadFailed')"
    />
    <p v-else-if="loading" class="loading-note" data-testid="decision-graph-loading">
      {{ t('common.loading') }}
    </p>
    <a-empty
      v-else-if="!decisions.length"
      data-testid="decision-graph-empty"
      :description="t('ontology.decisionGraphEmpty')"
    />
    <template v-else>
      <label class="focus-row">
        <span class="focus-label">{{ t('ontology.decisionGraphFocus') }}</span>
        <a-select
          v-model:value="focusId"
          :options="focusOptions"
          class="focus-select mono"
          size="small"
          data-testid="decision-focus-select"
          @change="loadTrace"
        />
      </label>

      <p v-if="traceError" class="inline-error" data-testid="decision-trace-error">
        {{ t('ontology.decisionGraphLoadFailed') }}
      </p>
      <p v-else-if="traceLoading" class="loading-note" data-testid="decision-trace-loading">
        {{ t('common.loading') }}
      </p>

      <svg
        v-if="graphNodes.length"
        class="graph-svg"
        :viewBox="`0 0 ${WIDTH} ${height}`"
        data-testid="decision-graph-svg"
        role="img"
      >
        <text :x="PAD_X" :y="12" class="col-label">{{ t('ontology.decisionGraphUpstream') }}</text>
        <text :x="DOWN_X" :y="12" class="col-label">{{ t('ontology.decisionGraphDownstream') }}</text>

        <g
          v-for="edge in graphEdges"
          :key="edge.key"
          class="dedge"
          :class="`dedge--${edge.kind}`"
          data-testid="decision-edge"
          :data-kind="edge.kind"
        >
          <path :d="edge.path" class="edge-path" />
          <text :x="edge.mx" :y="edge.my" class="edge-label">{{ edge.kind }}</text>
        </g>

        <g
          v-for="node in graphNodes"
          :key="node.id"
          class="dnode"
          :class="{ 'dnode--focus': node.isFocus }"
          data-testid="decision-node"
          :data-node-id="node.id"
        >
          <rect :x="node.x" :y="node.y" :width="NODE_W" :height="NODE_H" rx="10" class="node-box" />
          <text :x="node.x + 10" :y="node.y + 19" class="node-line1">{{ node.line1 }}</text>
          <text :x="node.x + 10" :y="node.y + 34" class="node-line2">{{ node.line2 }}</text>
        </g>
      </svg>

      <p class="graph-stats" data-testid="decision-graph-stats">
        {{ graphNodes.length }} {{ t('ontology.graphNodes') }} ·
        {{ graphEdges.length }} {{ t('ontology.graphEdges') }}
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 决策因果图（U7，只读）：节点＝决策（GET /knowledge/ontology/decisions），
 * 边＝caused/influenced/precedent（GET .../decisions/{id}/trace 闭包读数）。
 * 后端语义即「影响图＝闭包」（knowledge_ontology.py trace 端点注释），故
 * 本图以焦点决策为中心：上游闭包在左、下游闭包在右；caused/precedent 无环
 * 由后端硬校验（decision_ledger.linkDecisions），influenced 允许环由 trace
 * 的 seen 集合去重。布局为分层 SVG 简实现，不引入图库依赖。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import { listOntologyDecisions, traceOntologyDecision } from '@/api/modules/ontology'
import { truncateText } from '@/utils/ontologyFormat'
import type { OntologyDecisionChainNode, OntologyDecisionRow } from '@/types/ontology'

const { t } = useI18n()

const NODE_W = 190
const NODE_H = 46
const GAP_Y = 14
const COL_GAP = 64
const PAD_X = 16
const TOP = 34
const WIDTH = PAD_X * 2 + NODE_W * 3 + COL_GAP * 2
const UP_X = PAD_X
const FOCUS_X = PAD_X + NODE_W + COL_GAP
const DOWN_X = FOCUS_X + NODE_W + COL_GAP

const decisions = ref<OntologyDecisionRow[]>([])
const focusId = ref('')
const chain = ref<OntologyDecisionChainNode[]>([])
const loading = ref(false)
const loadError = ref(false)
const traceLoading = ref(false)
const traceError = ref(false)

const byId = computed(() => {
  const map = new Map<string, OntologyDecisionRow>()
  for (const d of decisions.value) map.set(d.decision_id, d)
  return map
})

interface GraphNode {
  id: string
  x: number
  y: number
  line1: string
  line2: string
  isFocus: boolean
}

interface GraphEdge {
  key: string
  kind: string
  path: string
  mx: number
  my: number
}

const upNodes = computed(() => chain.value.filter((c) => c.side === 'up'))
const downNodes = computed(() => chain.value.filter((c) => c.side === 'down'))

const focusOptions = computed(() =>
  decisions.value.map((d) => ({ value: d.decision_id, label: decisionLabel(d) })),
)

const columnHeight = computed(() => {
  const rows = Math.max(upNodes.value.length, downNodes.value.length, 1)
  return rows * (NODE_H + GAP_Y) - GAP_Y
})

const height = computed(() => Math.max(columnHeight.value + TOP + 16, 150))

const focusY = computed(() => TOP + (columnHeight.value - NODE_H) / 2)

function decisionLabel(d: OntologyDecisionRow): string {
  const head = d.scenario || d.category || d.decision_id
  return truncateText(`${d.category ? `[${d.category}] ` : ''}${head}`, 42)
}

function nodeLabel(id: string): { line1: string; line2: string } {
  const row = byId.value.get(id)
  if (!row) return { line1: truncateText(id, 24), line2: '' }
  return {
    line1: truncateText(row.scenario || row.decision_id, 24),
    line2: truncateText(`${row.category || '-'} · ${(row.confidence ?? 0).toFixed(2)}`, 24),
  }
}

const graphNodes = computed<GraphNode[]>(() => {
  if (!focusId.value) return []
  const nodes: GraphNode[] = []
  const focusLabel = nodeLabel(focusId.value)
  nodes.push({ id: focusId.value, x: FOCUS_X, y: focusY.value, ...focusLabel, isFocus: true })
  upNodes.value.forEach((c, i) => {
    const label = nodeLabel(c.decision_id)
    nodes.push({ id: c.decision_id, x: UP_X, y: TOP + i * (NODE_H + GAP_Y), ...label, isFocus: false })
  })
  downNodes.value.forEach((c, i) => {
    const label = nodeLabel(c.decision_id)
    nodes.push({ id: c.decision_id, x: DOWN_X, y: TOP + i * (NODE_H + GAP_Y), ...label, isFocus: false })
  })
  return nodes
})

const graphEdges = computed<GraphEdge[]>(() => {
  const edges: GraphEdge[] = []
  const fy = focusY.value + NODE_H / 2
  upNodes.value.forEach((c, i) => {
    const y = TOP + i * (NODE_H + GAP_Y) + NODE_H / 2
    const x1 = UP_X + NODE_W
    const x2 = FOCUS_X
    edges.push({
      key: `up-${c.decision_id}`,
      kind: c.link_kind,
      path: `M ${x1} ${y} C ${x1 + 28} ${y}, ${x2 - 28} ${fy}, ${x2} ${fy}`,
      mx: (x1 + x2) / 2,
      my: (y + fy) / 2 - 4,
    })
  })
  downNodes.value.forEach((c, i) => {
    const y = TOP + i * (NODE_H + GAP_Y) + NODE_H / 2
    const x1 = FOCUS_X + NODE_W
    const x2 = DOWN_X
    edges.push({
      key: `down-${c.decision_id}`,
      kind: c.link_kind,
      path: `M ${x1} ${fy} C ${x1 + 28} ${fy}, ${x2 - 28} ${y}, ${x2} ${y}`,
      mx: (x1 + x2) / 2,
      my: (fy + y) / 2 - 4,
    })
  })
  return edges
})

async function loadList() {
  loading.value = true
  loadError.value = false
  try {
    const res = await listOntologyDecisions(50)
    decisions.value = res.data ?? []
    if (!focusId.value && decisions.value.length) focusId.value = decisions.value[0].decision_id
  } catch {
    loadError.value = true
    decisions.value = []
  } finally {
    loading.value = false
  }
}

async function loadTrace() {
  if (!focusId.value) {
    chain.value = []
    return
  }
  traceLoading.value = true
  traceError.value = false
  try {
    const res = await traceOntologyDecision(focusId.value, 'both')
    chain.value = res.data?.chain ?? []
  } catch {
    traceError.value = true
    chain.value = []
  } finally {
    traceLoading.value = false
  }
}

async function reload() {
  await loadList()
  await loadTrace()
}

onMounted(reload)
</script>

<style scoped>
.decision-graph {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.view-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.view-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}
.loading-note {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.focus-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.focus-label {
  color: var(--nr-text-secondary, inherit);
  white-space: nowrap;
}
.focus-select {
  flex: 1;
  min-width: 0;
  max-width: 460px;
  padding: 5px 8px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.3));
  background: transparent;
  color: var(--nr-text-primary, inherit);
  font-size: 12px;
}
.inline-error {
  margin: 0;
  font-size: 12px;
  color: var(--nr-error, inherit);
}
.graph-svg {
  width: 100%;
  max-width: 760px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 10px;
}
.col-label {
  font-size: 10px;
  fill: var(--nr-text-secondary, inherit);
}
.node-box {
  fill: var(--nr-glass-bg, rgba(128, 128, 128, 0.08));
  stroke: var(--nr-glass-border, rgba(128, 128, 128, 0.3));
}
.dnode--focus .node-box {
  fill: var(--nr-primary-soft, rgba(99, 102, 241, 0.12));
  stroke: var(--nr-primary, #6366f1);
}
.node-line1 {
  font-size: 11px;
  fill: var(--nr-text-primary, inherit);
}
.node-line2 {
  font-size: 9px;
  fill: var(--nr-text-secondary, inherit);
}
.edge-path {
  fill: none;
  stroke-width: 1.5;
}
.dedge--caused .edge-path { stroke: var(--nr-primary, #6366f1); }
.dedge--influenced .edge-path { stroke: var(--nr-accent, #22d3ee); }
.dedge--precedent .edge-path { stroke: var(--nr-accent-secondary, #a78bfa); }
.edge-label {
  font-size: 9px;
  fill: var(--nr-text-secondary, inherit);
}
.graph-stats {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
</style>
