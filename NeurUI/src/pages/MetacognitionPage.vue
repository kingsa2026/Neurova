<template>
  <div class="metacognition-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('nav.metacognition') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <GlassButton variant="primary" :loading="triggering" @click="triggerMetacognition">
        {{ t('agent.rebuildLoop') }}
      </GlassButton>
    </div>

    <a-spin :spinning="loading">
      <!-- Current state metrics -->
      <div class="metrics-grid">
        <GlassCard v-for="metric in metrics" :key="metric.label" variant="subtle">
          <div class="metric-card">
            <div class="metric-header">
              <span class="metric-label">{{ metric.label }}</span>
              <a-tag :color="metric.color">{{ metric.status }}</a-tag>
            </div>
            <div class="metric-value">{{ metric.displayValue }}</div>
            <a-progress
              :percent="metric.percent"
              :stroke-color="metric.color"
              :show-info="false"
              size="small"
            />
          </div>
        </GlassCard>
      </div>

      <!-- Detailed state -->
      <GlassCard :title="t('memory.overview')" style="margin-top: 20px">
        <div v-if="metaState" class="state-details">
          <a-descriptions :column="2" bordered size="small">
            <a-descriptions-item :label="t('common.status')">
              <a-badge :status="stateBadge" :text="metaState.state || 'unknown'" />
            </a-descriptions-item>
            <a-descriptions-item label="Confidence">
              {{ formatPercent(metaState.confidence) }}
            </a-descriptions-item>
            <a-descriptions-item label="Uncertainty">
              {{ formatPercent(metaState.uncertainty) }}
            </a-descriptions-item>
            <a-descriptions-item label="Awareness">
              {{ formatPercent(metaState.awareness) }}
            </a-descriptions-item>
            <a-descriptions-item label="Self-monitoring">
              {{ formatPercent(metaState.self_monitoring) }}
            </a-descriptions-item>
            <a-descriptions-item label="Adaptation Rate">
              {{ formatPercent(metaState.adaptation_rate) }}
            </a-descriptions-item>
          </a-descriptions>
        </div>
        <a-empty v-else :description="t('common.noData')" />
      </GlassCard>

      <!-- Cognitive dimensions -->
      <GlassCard :title="t('growth.traits')" style="margin-top: 20px">
        <div v-if="dimensions.length > 0" class="dimensions-list">
          <div v-for="dim in dimensions" :key="dim.name" class="dimension-row">
            <div class="dim-info">
              <span class="dim-name">{{ dim.name }}</span>
              <span class="dim-value">{{ formatPercent(dim.value) }}</span>
            </div>
            <a-progress
              :percent="Math.round((dim.value || 0) * 100)"
              :stroke-color="dim.value >= 0.7 ? '#10b981' : dim.value >= 0.4 ? '#6366f1' : '#f59e0b'"
              size="small"
            />
          </div>
        </div>
        <a-empty v-else :description="t('common.noData')" />
      </GlassCard>

      <!-- History log -->
      <GlassCard :title="t('memory.timeline')" style="margin-top: 20px">
        <a-table
          v-if="history.length > 0"
          :columns="historyColumns"
          :data-source="history"
          :pagination="{ pageSize: 10 }"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'confidence'">
              <a-progress
                :percent="Math.round((record.confidence || 0) * 100)"
                size="small"
                :show-info="false"
                style="width: 80px"
              />
            </template>
            <template v-else-if="column.key === 'trigger'">
              <a-tag>{{ record.trigger || 'manual' }}</a-tag>
            </template>
          </template>
        </a-table>
        <a-empty v-else :description="t('common.noData')" />
      </GlassCard>
    </a-spin>
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
const triggering = ref(false)
const metaState = ref<any>(null)
const history = ref<any[]>([])

const formatPercent = (val: number | undefined) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const metrics = computed(() => {
  if (!metaState.value) return []
  return [
    {
      label: 'Confidence',
      displayValue: formatPercent(metaState.value.confidence),
      percent: Math.round((metaState.value.confidence || 0) * 100),
      color: '#10b981',
      status: (metaState.value.confidence || 0) >= 0.7 ? 'High' : 'Low',
    },
    {
      label: 'Uncertainty',
      displayValue: formatPercent(metaState.value.uncertainty),
      percent: Math.round((metaState.value.uncertainty || 0) * 100),
      color: '#f59e0b',
      status: (metaState.value.uncertainty || 0) <= 0.3 ? 'Low' : 'High',
    },
    {
      label: 'Awareness',
      displayValue: formatPercent(metaState.value.awareness),
      percent: Math.round((metaState.value.awareness || 0) * 100),
      color: '#6366f1',
      status: (metaState.value.awareness || 0) >= 0.7 ? 'High' : 'Low',
    },
    {
      label: 'Self-Monitoring',
      displayValue: formatPercent(metaState.value.self_monitoring),
      percent: Math.round((metaState.value.self_monitoring || 0) * 100),
      color: '#8b5cf6',
      status: (metaState.value.self_monitoring || 0) >= 0.5 ? 'Active' : 'Passive',
    },
  ]
})

const dimensions = computed(() => {
  if (!metaState.value?.dimensions) return []
  return Object.entries(metaState.value.dimensions).map(([name, value]) => ({
    name,
    value: value as number,
  }))
})

const stateBadge = computed(() => {
  const s = metaState.value?.state
  if (s === 'active' || s === 'healthy') return 'success'
  if (s === 'degraded') return 'warning'
  return 'default'
})

const historyColumns = computed(() => [
  { title: t('common.createdAt'), dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: 'Confidence', key: 'confidence', width: 120 },
  { title: 'Trigger', key: 'trigger', width: 120 },
  { title: t('common.description'), dataIndex: 'summary', key: 'summary', ellipsis: true },
])

const fetchMetacognition = async () => {
  loading.value = true
  try {
    const res: any = await request.get(`/metacognition/${agentId.value}/metacognition`)
    const data = res?.data ?? res
    metaState.value = data?.state ?? data?.current ?? data
    history.value = data?.history ?? data?.logs ?? []
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const triggerMetacognition = async () => {
  triggering.value = true
  try {
    await request.post(`/metacognition/${agentId.value}/metacognition/trigger`)
    message.success(t('common.success'))
    await fetchMetacognition()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    triggering.value = false
  }
}

onMounted(() => {
  fetchMetacognition()
})
</script>

<style scoped>
.metacognition-page {
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

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

.metric-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.metric-label {
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.metric-value {
  font-family: var(--nr-font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--nr-text-primary);
}

.state-details {
  padding: 4px 0;
}

.dimensions-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dimension-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dim-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dim-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
  text-transform: capitalize;
}

.dim-value {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
}
</style>
