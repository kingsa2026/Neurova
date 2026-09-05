<template>
  <div class="knowledge-graph-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('knowledge.graph') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <GlassButton variant="secondary" :loading="loading" @click="fetchGraph">
        {{ t('common.refresh') }}
      </GlassButton>
    </div>

    <!-- Stats cards -->
    <div class="stats-grid">
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ graphData.nodes?.length || 0 }}</div>
          <div class="stat-label">{{ t('workflow.nodes') }}</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ graphData.edges?.length || 0 }}</div>
          <div class="stat-label">{{ t('knowledge.edges') }}</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ uniqueCategories.length }}</div>
          <div class="stat-label">{{ t('memory.categories') }}</div>
        </div>
      </GlassCard>
    </div>

    <!-- Search & Graph area -->
    <GlassCard>
      <div class="toolbar">
        <a-input-search
          v-model:value="searchQuery"
          :placeholder="t('knowledge.search')"
          style="max-width: 360px"
          allow-clear
        />
        <div class="category-filters">
          <a-tag
            v-for="cat in uniqueCategories"
            :key="cat"
            :color="selectedCategory === cat ? 'blue' : 'default'"
            class="category-tag"
            @click="toggleCategory(cat)"
          >
            {{ cat }}
          </a-tag>
        </div>
      </div>

      <a-spin :spinning="loading">
        <div class="graph-container">
          <div v-if="filteredNodes.length === 0 && !loading" class="graph-empty">
            <a-empty :description="t('common.noData')" />
          </div>
          <!-- ECharts force 图（补课 2.4：替换 node-grid 卡片假图） -->
          <VChart v-else class="graph-chart" :option="chartOption" autoresize />
        </div>
      </a-spin>
    </GlassCard>

    <!-- Node detail panel -->
    <GlassCard v-if="selectedNode" :title="selectedNode.label || selectedNode.name">
      <div class="node-detail">
        <div class="detail-row">
          <span class="detail-label">{{ t('knowledge.id') }}</span>
          <span class="detail-value mono">{{ selectedNode.id }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">{{ t('memory.categories') }}</span>
          <a-tag>{{ selectedNode.category || 'default' }}</a-tag>
        </div>
        <div v-if="selectedNode.description" class="detail-row">
          <span class="detail-label">{{ t('common.description') }}</span>
          <span class="detail-value">{{ selectedNode.description }}</span>
        </div>
        <div v-if="selectedNode.metadata" class="detail-row">
          <span class="detail-label">{{ t('knowledge.metadata') }}</span>
          <pre class="detail-value mono">{{ JSON.stringify(selectedNode.metadata, null, 2) }}</pre>
        </div>
        <div v-if="nodeEdges.length > 0" class="detail-section">
          <h4>Connections ({{ nodeEdges.length }})</h4>
          <div v-for="(edge, i) in nodeEdges" :key="i" class="edge-item">
            <span class="mono">{{ edge.source }}</span>
            <span class="edge-arrow">&rarr;</span>
            <span class="mono">{{ edge.target }}</span>
            <a-tag v-if="edge.relation" size="small">{{ edge.relation }}</a-tag>
          </div>
        </div>
      </div>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useAppStore } from '@/stores/app'
import { request } from '@/api'
import VChart from 'vue-echarts'
import {
  buildTooltipOption,
  buildTooltipFormatter,
  buildNodeLabelOption,
  buildEdgeLabelOption,
  categoryColor,
  tooltipTextClass,
} from '@/pages/knowledge-graph/chartOptions'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()
const appStore = useAppStore()

const loading = ref(false)
const searchQuery = ref('')
const selectedCategory = ref<string | null>(null)
const selectedNode = ref<any>(null)
const graphData = ref<{ nodes: any[]; edges: any[] }>({ nodes: [], edges: [] })

// 归一化：后端节点 {id,label,type,description,weight} / 边 {source,target,relation,weight}
const normalizeNode = (n: any) => ({
  ...n,
  category: n.category ?? n.type ?? 'default',
  name: n.label ?? n.name ?? n.id,
})

const uniqueCategories = computed(() => {
  const cats = new Set<string>()
  graphData.value.nodes?.forEach((raw) => {
    const n = normalizeNode(raw)
    if (n.category) cats.add(n.category)
  })
  return Array.from(cats)
})

const filteredNodes = computed(() => {
  let nodes = (graphData.value.nodes || []).map(normalizeNode)
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    nodes = nodes.filter(
      (n) =>
        (n.label || '').toLowerCase().includes(q) ||
        (n.name || '').toLowerCase().includes(q) ||
        (n.id || '').toLowerCase().includes(q),
    )
  }
  if (selectedCategory.value) {
    nodes = nodes.filter((n) => n.category === selectedCategory.value)
  }
  return nodes
})

const nodeEdges = computed(() => {
  if (!selectedNode.value) return []
  return (graphData.value.edges || []).filter(
    (e) => e.source === selectedNode.value.id || e.target === selectedNode.value.id,
  )
})

const chartOption = computed(() => {
  const theme = { isDark: appStore.isDark }
  const nodes = filteredNodes.value.map((n: any) => ({
    id: n.id,
    name: n.label || n.name,
    category: n.category,
    value: n.weight ?? 1,
    description: n.description,
    itemStyle: { color: categoryColor(n.category) },
    symbolSize: 18 + Math.min(30, (n.connections ?? 0) * 3 + (n.weight ?? 0) * 6),
  }))
  const ids = new Set(nodes.map((n: any) => n.id))
  const links = (graphData.value.edges || [])
    .filter((e: any) => ids.has(e.source) && ids.has(e.target))
    .map((e: any) => ({
      source: e.source,
      target: e.target,
      relation: e.relation,
      lineStyle: { width: Math.max(1, Math.min(4, e.weight ?? 1)) },
    }))
  return {
    tooltip: {
      ...buildTooltipOption(),
      className: `${buildTooltipOption().className} ${tooltipTextClass(theme)}`,
      formatter: buildTooltipFormatter(),
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        data: nodes,
        links,
        force: { repulsion: 160, edgeLength: [60, 140], gravity: 0.08 },
        label: buildNodeLabelOption(theme),
        labelLayout: { hideOverlap: true },
        emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
        edgeLabel: buildEdgeLabelOption(theme),
        lineStyle: { color: 'source', curveness: 0.15, opacity: 0.7 },
      },
    ],
  }
})

const toggleCategory = (cat: string) => {
  selectedCategory.value = selectedCategory.value === cat ? null : cat
}

const fetchGraph = async () => {
  loading.value = true
  try {
    const res: any = await request.get(`/knowledge-graph/${agentId.value}/knowledge-graph`)
    const data = res?.data ?? res
    graphData.value = {
      nodes: data?.nodes ?? data?.items ?? [],
      edges: data?.edges ?? data?.relations ?? [],
    }
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchGraph()
})
</script>

<style scoped>
.knowledge-graph-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary);
  font-size: 13px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.stat-item {
  text-align: center;
  padding: 8px 0;
}

.stat-value {
  font-family: var(--nr-font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--nr-text-primary);
  line-height: 1.1;
}

.stat-label {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 6px;
}

.toolbar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.category-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.category-tag {
  cursor: pointer;
  user-select: none;
}

.graph-container {
  min-height: 420px;
}

.graph-chart {
  width: 100%;
  height: 420px;
}

.graph-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

.node-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-label {
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.detail-value {
  font-size: 13px;
  color: var(--nr-text-primary);
}

.mono {
  font-family: var(--nr-font-mono);
}

.detail-section {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--nr-glass-border);
}

.detail-section h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin: 0 0 10px;
}

.edge-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.edge-arrow {
  color: var(--nr-text-tertiary);
}

pre.detail-value {
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  background: rgba(255, 255, 255, 0.03);
  padding: 8px 12px;
  border-radius: 6px;
  margin: 0;
}
</style>

<style>
/* ECharts tooltip 挂在图表容器内（appendToBody:false），非 scoped 可达 */
.kg-graph-tooltip.kg-tooltip--dark {
  background: rgba(15, 23, 42, 0.96);
  color: #e2e8f0;
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.kg-graph-tooltip.kg-tooltip--light {
  background: rgba(255, 255, 255, 0.98);
  color: #1e293b;
  border: 1px solid rgba(100, 116, 139, 0.3);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
}
</style>
