<template>
  <div class="genealogy" data-testid="studio-derivation-genealogy">
    <div class="view-head">
      <h4 class="view-title">{{ t('ontology.genealogyTitle') }}</h4>
      <GlassButton
        size="sm"
        variant="secondary"
        :loading="buildLoading"
        data-testid="genealogy-refresh"
        @click="rebuild"
      >
        {{ t('ontology.genealogyRefresh') }}
      </GlassButton>
    </div>

    <a-alert
      v-if="listError"
      type="error"
      show-icon
      data-testid="genealogy-error"
      :message="t('ontology.genealogyLoadFailed')"
    />
    <p v-else-if="listLoading" class="loading-note" data-testid="genealogy-loading">
      {{ t('common.loading') }}
    </p>
    <a-empty
      v-else-if="!facts.length"
      data-testid="genealogy-empty"
      :description="t('ontology.genealogyEmpty')"
    />
    <template v-else>
      <div class="query-row">
        <input
          v-model="queryText"
          class="query-input"
          :placeholder="t('ontology.genealogyFactLabel')"
          data-testid="genealogy-query"
          @keyup.enter="searchFacts"
        />
        <GlassButton size="sm" data-testid="genealogy-search" @click="searchFacts">
          {{ t('common.search') }}
        </GlassButton>
        <a-select
          v-model:value="rootId"
          :options="factOptions"
          class="fact-select mono"
          size="small"
          data-testid="genealogy-fact-select"
          @change="rebuild"
        />
      </div>

      <p v-if="buildError" class="inline-error" data-testid="genealogy-build-error">
        {{ t('ontology.genealogyLoadFailed') }}
      </p>
      <p v-else-if="buildLoading" class="loading-note" data-testid="genealogy-build-loading">
        {{ t('common.loading') }}
      </p>
      <p v-else-if="observedRoot" class="observed-note" data-testid="genealogy-observed-note">
        {{ t('ontology.genealogyNoDerivation') }}
      </p>

      <svg
        v-if="layout.length"
        class="genealogy-svg"
        :viewBox="`0 0 ${WIDTH} ${svgHeight}`"
        data-testid="genealogy-svg"
        role="img"
      >
        <g
          v-for="edge in layoutEdges"
          :key="edge.key"
          class="gedge"
          data-testid="genealogy-edge"
          :data-rule="edge.ruleId"
        >
          <path :d="edge.path" class="edge-path" />
          <text v-if="edge.ruleId" :x="edge.mx" :y="edge.my" class="edge-label">{{ edge.ruleId }}</text>
        </g>
        <g
          v-for="node in layout"
          :key="node.factId"
          class="gnode"
          :class="`gnode--${node.kind}`"
          data-testid="genealogy-node"
          :data-fact-id="node.factId"
          :data-depth="node.depth"
        >
          <rect :x="node.x" :y="node.y" :width="node.w" :height="NODE_H" :rx="node.rx" class="node-box" />
          <text :x="node.x + 10" :y="node.y + 17" class="node-line1">{{ node.line1 }}</text>
          <text :x="node.x + 10" :y="node.y + 31" class="node-line2">{{ node.line2 }}</text>
        </g>
      </svg>

      <p class="graph-stats" data-testid="genealogy-stats">
        {{ layout.length }} {{ t('ontology.graphNodes') }} ·
        {{ layoutEdges.length }} {{ t('ontology.graphEdges') }}
      </p>
      <p class="legend">
        <span class="legend-item"><span class="swatch swatch--derived" />{{ t('ontology.genealogyDerived') }}</span>
        <span class="legend-item"><span class="swatch swatch--observed" />{{ t('ontology.genealogyObserved') }}</span>
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 推导谱系（U7，只读）：POST /knowledge/access/query（knownAt=当前时刻 →
 * 事实层命中，knowledge_id＝fact_id）选根事实；GET /knowledge/ontology/
 * derivations/{fact_id} 逐层展开 premises→conclusion 分层 DAG。节点按来源
 * 分色分形：规则推导（derived）实线圆角矩形，观察事实（observed）虚线胶囊；
 * 深度上限 3、节点上限 24（超出截断，诚实标注不伪称全量）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import { accessQuery, getDerivationChain } from '@/api/modules/ontology'
import { truncateText } from '@/utils/ontologyFormat'
import type { DerivationChain, FactQueryItem } from '@/types/ontology'

const { t } = useI18n()

const MAX_DEPTH = 3
const MAX_NODES = 24
const WIDTH = 760
const PAD_X = 16
const TOP = 20
const NODE_H = 40
const LAYER_GAP = 64

interface GenealogyNode {
  factId: string
  label: string
  kind: 'root' | 'derived' | 'observed'
  ruleId: string
  depth: number
}

interface GenealogyEdge {
  from: string
  to: string
  ruleId: string
}

const facts = ref<FactQueryItem[]>([])
const queryText = ref('')
const rootId = ref('')
const nodes = ref<GenealogyNode[]>([])
const edges = ref<GenealogyEdge[]>([])
const observedRoot = ref(false)
const listLoading = ref(false)
const listError = ref(false)
const buildLoading = ref(false)
const buildError = ref(false)

function factIdOf(f: FactQueryItem): string {
  return f.knowledge_id || f.id || ''
}

function factLabel(f: FactQueryItem): string {
  const meta = (f.metadata ?? {}) as Record<string, unknown>
  const triple = `${meta.subject_key ?? ''}·${meta.predicate_term_id ?? ''}·${meta.object_term ?? ''}`
  const text = f.title && f.title !== ' · ' ? f.title : triple
  const id = factIdOf(f)
  const short = id.length > 14 ? `${id.slice(0, 14)}…` : id
  return `${short} ${text}`.trim().slice(0, 60)
}

function shortId(id: string): string {
  return id.length > 18 ? `${id.slice(0, 17)}…` : id
}

const factOptions = computed(() =>
  facts.value.map((f) => ({ value: factIdOf(f), label: factLabel(f) })),
)

async function loadFacts() {
  listLoading.value = true
  listError.value = false
  try {
    const body: Record<string, unknown> = {
      query: queryText.value.trim(),
      knownAt: new Date().toISOString(),
      limit: 50,
    }
    const res = await accessQuery(body as never)
    const payload = (res as unknown as { data?: unknown }).data ?? res
    facts.value = Array.isArray(payload) ? (payload as FactQueryItem[]) : []
    if (!facts.value.some((f) => factIdOf(f) === rootId.value)) {
      rootId.value = facts.value.length ? factIdOf(facts.value[0]) : ''
    }
  } catch {
    listError.value = true
    facts.value = []
  } finally {
    listLoading.value = false
  }
}

function searchFacts() {
  void (async () => {
    await loadFacts()
    await buildGenealogy()
  })()
}

async function fetchChain(factId: string): Promise<DerivationChain | null> {
  try {
    const res = await getDerivationChain(factId)
    return (res.data ?? null) as DerivationChain | null
  } catch {
    // 404（条目型命中或事实缺行）＝无推导记录，按观察事实呈现，不伪造解释
    return null
  }
}

async function buildGenealogy() {
  if (!rootId.value) {
    nodes.value = []
    edges.value = []
    observedRoot.value = false
    return
  }
  buildLoading.value = true
  buildError.value = false
  try {
    const nextNodes: GenealogyNode[] = []
    const nextEdges: GenealogyEdge[] = []
    const edgeKeys = new Set<string>()
    const visited = new Set<string>()
    const rootLabel = factLabel(facts.value.find((f) => factIdOf(f) === rootId.value) ?? { title: '', id: rootId.value } as FactQueryItem)
    const rootChain = await fetchChain(rootId.value)
    const rootDerived = !!rootChain?.derived && (rootChain.premise_count ?? 0) > 0
    observedRoot.value = !rootDerived

    type QueueItem = { factId: string; depth: number; label: string }
    const queue: QueueItem[] = [{ factId: rootId.value, depth: 0, label: rootLabel }]
    while (queue.length && nextNodes.length < MAX_NODES) {
      const item = queue.shift() as QueueItem
      if (visited.has(item.factId)) continue
      visited.add(item.factId)
      const chain = await fetchChain(item.factId)
      const derived = !!chain?.derived && (chain.premise_count ?? 0) > 0
      nextNodes.push({
        factId: item.factId,
        label: item.label || shortId(item.factId),
        kind: item.depth === 0 ? 'root' : derived ? 'derived' : 'observed',
        ruleId: chain?.rule_id ?? '',
        depth: item.depth,
      })
      if (derived && item.depth < MAX_DEPTH) {
        for (const p of chain?.premises ?? []) {
          if (!p.premise_fact_id) continue
          const key = `${p.premise_fact_id}->${item.factId}`
          if (!edgeKeys.has(key)) {
            edgeKeys.add(key)
            nextEdges.push({ from: p.premise_fact_id, to: item.factId, ruleId: chain?.rule_id ?? '' })
          }
          if (!visited.has(p.premise_fact_id)) {
            queue.push({ factId: p.premise_fact_id, depth: item.depth + 1, label: '' })
          }
        }
      }
    }
    nodes.value = nextNodes
    edges.value = nextEdges
  } catch {
    buildError.value = true
    nodes.value = []
    edges.value = []
  } finally {
    buildLoading.value = false
  }
}

async function rebuild() {
  await buildGenealogy()
}

// ── 分层布局：第 0 层（结论）在顶，premises 逐层向下 ─────────────

interface LayoutNode extends GenealogyNode {
  x: number
  y: number
  w: number
  rx: number
  line1: string
  line2: string
}

const maxDepth = computed(() => nodes.value.reduce((m, n) => Math.max(m, n.depth), 0))

const svgHeight = computed(() => TOP * 2 + (maxDepth.value + 1) * (NODE_H + LAYER_GAP) - LAYER_GAP)

const layout = computed<LayoutNode[]>(() => {
  const out: LayoutNode[] = []
  for (let depth = 0; depth <= maxDepth.value; depth += 1) {
    const layer = nodes.value.filter((n) => n.depth === depth)
    if (!layer.length) continue
    const innerW = WIDTH - PAD_X * 2
    const w = Math.min(190, Math.floor(innerW / layer.length) - 10)
    const y = TOP + depth * (NODE_H + LAYER_GAP)
    layer.forEach((n, i) => {
      const cx = PAD_X + (i + 0.5) * (innerW / layer.length)
      out.push({
        ...n,
        x: Math.max(PAD_X, cx - w / 2),
        y,
        w,
        rx: n.kind === 'observed' ? 18 : 8,
        line1: n.kind === 'root' ? truncateText(n.label, 22) : n.label,
        line2: kindText(n),
      })
    })
  }
  return out
})

function kindText(n: GenealogyNode): string {
  if (n.kind === 'observed') return t('ontology.genealogyObserved')
  if (n.kind === 'derived') return `${t('ontology.genealogyDerived')} · ${n.ruleId}`.trim()
  return n.ruleId ? `${t('ontology.genealogyDerived')} · ${n.ruleId}`.trim() : t('ontology.genealogyDerived')
}

interface LayoutEdge {
  key: string
  path: string
  mx: number
  my: number
  ruleId: string
}

const layoutEdges = computed<LayoutEdge[]>(() => {
  const pos = new Map<string, { cx: number; y: number }>()
  for (const n of layout.value) pos.set(n.factId, { cx: n.x + n.w / 2, y: n.y })
  return edges.value
    .filter((e) => pos.has(e.from) && pos.has(e.to))
    .map((e) => {
      const from = pos.get(e.from) as { cx: number; y: number }
      const to = pos.get(e.to) as { cx: number; y: number }
      const y1 = from.y + NODE_H
      const y2 = to.y
      const mx = (from.cx + to.cx) / 2
      const my = (y1 + y2) / 2 + 4
      return {
        key: `${e.from}->${e.to}`,
        path: `M ${from.cx} ${y1} C ${from.cx} ${y1 + 24}, ${to.cx} ${y2 - 24}, ${to.cx} ${y2}`,
        mx,
        my,
        ruleId: e.ruleId,
      }
    })
})

onMounted(() => {
  void (async () => {
    await loadFacts()
    await buildGenealogy()
  })()
})
</script>

<style scoped>
.genealogy {
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
.query-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.query-input {
  flex: 1;
  min-width: 200px;
  max-width: 320px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.3));
  background: transparent;
  color: var(--nr-text-primary, inherit);
  font-size: 12px;
}
.fact-select {
  flex: 1;
  min-width: 220px;
  max-width: 380px;
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
.observed-note {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.genealogy-svg {
  width: 100%;
  max-width: 800px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 10px;
}
.node-box {
  fill: var(--nr-glass-bg, rgba(128, 128, 128, 0.08));
  stroke: var(--nr-glass-border, rgba(128, 128, 128, 0.3));
}
.gnode--root .node-box {
  fill: var(--nr-primary-soft, rgba(99, 102, 241, 0.12));
  stroke: var(--nr-primary, #6366f1);
}
.gnode--derived .node-box {
  fill: var(--nr-primary-soft, rgba(99, 102, 241, 0.1));
  stroke: var(--nr-accent-secondary, #a78bfa);
}
.gnode--observed .node-box {
  fill: transparent;
  stroke: var(--nr-text-secondary, rgba(128, 128, 128, 0.6));
  stroke-dasharray: 4 3;
}
.node-line1 {
  font-size: 10px;
  fill: var(--nr-text-primary, inherit);
}
.node-line2 {
  font-size: 9px;
  fill: var(--nr-text-secondary, inherit);
}
.edge-path {
  fill: none;
  stroke: var(--nr-glass-border-strong, rgba(128, 128, 128, 0.4));
  stroke-width: 1.2;
}
.edge-label {
  font-size: 8px;
  fill: var(--nr-text-secondary, inherit);
}
.graph-stats {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.legend {
  margin: 0;
  display: flex;
  gap: 14px;
  font-size: 11px;
  color: var(--nr-text-secondary, inherit);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.swatch {
  display: inline-block;
  width: 14px;
  height: 10px;
  border-radius: 3px;
}
.swatch--derived {
  background: var(--nr-primary-soft, rgba(99, 102, 241, 0.1));
  border: 1px solid var(--nr-accent-secondary, #a78bfa);
}
.swatch--observed {
  background: transparent;
  border: 1px dashed var(--nr-text-secondary, rgba(128, 128, 128, 0.6));
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
</style>
