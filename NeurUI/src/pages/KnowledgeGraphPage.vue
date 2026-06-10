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
          <div class="stat-label">Edges</div>
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
          @search="filterNodes"
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
          <div v-else class="node-grid">
            <div
              v-for="node in filteredNodes"
              :key="node.id"
              class="graph-node"
              :class="{ 'is-selected': selectedNode?.id === node.id }"
              @click="selectNode(node)"
            >
              <div class="node-label">{{ node.label || node.name }}</div>
              <a-tag size="small">{{ node.category || 'default' }}</a-tag>
              <div v-if="node.connections" class="node-connections">
                {{ node.connections }} connections
              </div>
            </div>
          </div>
        </div>
      </a-spin>
    </GlassCard>

    <!-- Node detail panel -->
    <GlassCard v-if="selectedNode" :title="selectedNode.label || selectedNode.name">
      <div class="node-detail">
        <div class="detail-row">
          <span class="detail-label">ID</span>
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
          <span class="detail-label">Metadata</span>
          <pre class="detail-value mono">{{ JSON.stringify(selectedNode.metadata, null, 2) }}</pre>
        </div>
        <div v-if="nodeEdges.length > 0" class="detail-section">
          <h4>Connections ({{ nodeEdges.length }})</h4>
          <div v-for="edge in nodeEdges" :key="edge.id" class="edge-item">
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
import { request } from '@/api'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()

const loading = ref(false)
const searchQuery = ref('')
const selectedCategory = ref<string | null>(null)
const selectedNode = ref<any>(null)
const graphData = ref<{ nodes: any[]; edges: any[] }>({ nodes: [], edges: [] })

const uniqueCategories = computed(() => {
  const cats = new Set<string>()
  graphData.value.nodes?.forEach((n) => {
    if (n.category) cats.add(n.category)
  })
  return Array.from(cats)
})

const filteredNodes = computed(() => {
  let nodes = graphData.value.nodes || []
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

const toggleCategory = (cat: string) => {
  selectedCategory.value = selectedCategory.value === cat ? null : cat
}

const selectNode = (node: any) => {
  selectedNode.value = selectedNode.value?.id === node.id ? null : node
}

const filterNodes = () => {
  // Filtering is reactive via computed, this is just a trigger for the search input
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
  min-height: 300px;
}

.graph-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

.node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.graph-node {
  padding: 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  transition: all 0.2s ease;
}

.graph-node:hover {
  border-color: rgba(99, 102, 241, 0.4);
  background: rgba(99, 102, 241, 0.06);
}

.graph-node.is-selected {
  border-color: rgba(99, 102, 241, 0.6);
  background: rgba(99, 102, 241, 0.1);
}

.node-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin-bottom: 6px;
}

.node-connections {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  margin-top: 6px;
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
