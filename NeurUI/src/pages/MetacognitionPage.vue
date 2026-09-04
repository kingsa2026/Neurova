<template>
  <div class="metacognition-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('nav.metacognition') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="secondary" size="sm" :loading="reflecting" @click="handleReflect">
          {{ t('metacognition.triggerReflect') }}
        </GlassButton>
        <GlassButton variant="secondary" size="sm" :loading="entriesLoading" @click="refreshAll">
          {{ t('common.refresh') }}
        </GlassButton>
        <GlassButton variant="primary" :loading="createMutation.loading.value" @click="showCreateModal = true">
          {{ t('common.create') }}
        </GlassButton>
      </div>
    </div>

    <!-- Stats Dashboard -->
    <div class="stats-dashboard" v-if="stats">
      <GlassCard variant="subtle">
        <div class="stat-card">
          <span class="stat-label">{{ t('metacognition.totalEntries') }}</span>
          <span class="stat-value">{{ stats.total_entries }}</span>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-card">
          <span class="stat-label">{{ t('metacognition.avgConfidence') }}</span>
          <span class="stat-value">{{ formatPercent(stats.avg_confidence) }}</span>
          <a-progress
            :percent="Math.round((stats.avg_confidence || 0) * 100)"
            :stroke-color="stats.avg_confidence >= 0.7 ? '#10b981' : '#f59e0b'"
            :show-info="false"
            size="small"
          />
        </div>
      </GlassCard>
      <GlassCard v-for="typeItem in stats.by_type" :key="typeItem.type" variant="subtle">
        <div class="stat-card">
          <span class="stat-label">{{ formatType(typeItem.type) }}</span>
          <span class="stat-value">{{ typeItem.count }}</span>
          <a-tag :color="typeColorMap[typeItem.type] || 'default'" size="small">{{ typeItem.type }}</a-tag>
        </div>
      </GlassCard>
    </div>

    <!-- Trend Chart -->
    <GlassCard v-if="stats?.recent_trend?.length" :title="t('metacognition.recentTrend')" style="margin-top: 20px">
      <div class="trend-chart">
        <div
          v-for="(point, idx) in stats.recent_trend"
          :key="idx"
          class="trend-bar-wrapper"
        >
          <div
            class="trend-bar"
            :style="{ height: trendBarHeight(point.count) + 'px' }"
            :title="`${point.date}: ${point.count}`"
          ></div>
          <span class="trend-label">{{ formatDate(point.date) }}</span>
        </div>
      </div>
    </GlassCard>

    <a-spin :spinning="loading">
      <!-- Cognitive load metrics (real state from chat pipeline write-through) -->
      <div class="metrics-grid" style="margin-top: 20px">
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

      <!-- Current load state details -->
      <GlassCard :title="t('metacognition.loadState')" style="margin-top: 20px">
        <div v-if="loadState" class="state-details">
            <a-descriptions :column="2" bordered size="small">
            <a-descriptions-item :label="t('metacognition.loadLevel')">
              <a-badge :status="loadBadge" :text="loadState.load_level || 'unknown'" />
            </a-descriptions-item>
            <a-descriptions-item :label="t('metacognition.loadScore')">
              {{ formatPercent(loadState.load_score) }}
            </a-descriptions-item>
            <a-descriptions-item :label="t('metacognition.activeTasks')">
              {{ loadState.active_tasks }}
            </a-descriptions-item>
            <a-descriptions-item :label="t('metacognition.errorRate')">
              {{ formatPercent(loadState.error_rate) }}
            </a-descriptions-item>
            <a-descriptions-item :label="t('metacognition.responseTime')">
              {{ Math.round(loadState.response_time_ms || 0) }} ms
            </a-descriptions-item>
            <a-descriptions-item :label="t('metacognition.updatedAt')">
              {{ formatTime(loadState.created_at) || '-' }}
            </a-descriptions-item>
          </a-descriptions>
        </div>
        <a-empty v-else :description="t('common.noData')" />
      </GlassCard>

      <!-- Load factor composition -->
      <GlassCard :title="t('metacognition.loadFactors')" style="margin-top: 20px">
        <div v-if="factors.length > 0" class="dimensions-list">
          <div v-for="dim in factors" :key="dim.name" class="dimension-row">
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

      <!-- Entries with type filter -->
      <GlassCard :title="t('metacognition.entries')" style="margin-top: 20px">
        <template #extra>
          <a-select
            v-model:value="typeFilter"
            :placeholder="t('metacognition.filterByType')"
            allow-clear
            style="width: 180px"
            size="small"
            @change="onTypeFilterChange"
          >
            <a-select-option value="self_assessment">{{ t('metacognition.selfAssessment') }}</a-select-option>
            <a-select-option value="strategy">{{ t('metacognition.strategy') }}</a-select-option>
            <a-select-option value="monitoring">{{ t('metacognition.monitoring') }}</a-select-option>
            <a-select-option value="planning">{{ t('metacognition.planning') }}</a-select-option>
          </a-select>
        </template>

        <a-spin :spinning="entriesLoading">
          <div v-if="entryItems.length > 0" class="entries-list">
            <div v-for="entry in entryItems" :key="entry.id" class="entry-card">
              <div class="entry-header">
                <a-tag :color="typeColorMap[entry.type] || 'default'">{{ formatType(entry.type) }}</a-tag>
                <span class="entry-date">{{ formatTime(entry.created_at) }}</span>
              </div>
              <p class="entry-content">{{ entry.content }}</p>
              <div v-if="entry.context" class="entry-context">
                <span class="context-label">{{ t('metacognition.context') }}:</span> {{ entry.context }}
              </div>
              <div class="entry-footer">
                <div v-if="entry.confidence !== undefined && entry.confidence !== null" class="entry-confidence">
                  <span class="confidence-label">{{ t('metacognition.confidence') }}:</span>
                  <a-progress
                    :percent="Math.round(entry.confidence * 100)"
                    size="small"
                    :stroke-color="entry.confidence >= 0.7 ? '#10b981' : entry.confidence >= 0.4 ? '#6366f1' : '#f59e0b'"
                    style="width: 100px"
                  />
                </div>
              </div>
            </div>
          </div>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>

        <!-- Pagination -->
        <div v-if="entryTotal > entrySize" class="pagination-row">
          <a-pagination
            v-model:current="entryPage"
            :total="entryTotal"
            :page-size="entrySize"
            size="small"
            show-less-items
            @change="onEntryPageChange"
          />
        </div>
      </GlassCard>

      <!-- Structured lessons (insight compiler output) -->
      <GlassCard :title="t('metacognition.insights')" style="margin-top: 20px">
        <template #extra>
          <a-tag v-if="lessons.length" color="arcoblue">{{ t('metacognition.templateSource') }}</a-tag>
        </template>
        <a-spin :spinning="lessonsLoading">
          <div v-if="lessons.length > 0" class="entries-list">
            <div v-for="(lesson, idx) in lessons" :key="idx" class="entry-card">
              <div class="entry-header">
                <a-tag :color="operatorColor(lesson.operator)">{{ lesson.operator }}</a-tag>
                <a-tag :color="lesson.recommendation === 'avoid_tool' ? 'red' : 'blue'">
                  {{ lesson.recommendation }}
                </a-tag>
                <span class="entry-date">{{ lesson.subject }}</span>
              </div>
              <p class="entry-content">{{ lesson.text }}</p>
            </div>
          </div>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </GlassCard>

      <!-- Reflection history -->
      <GlassCard :title="t('metacognition.reflectionHistory')" style="margin-top: 20px">
        <a-table
          v-if="history.length > 0"
          :columns="historyColumns"
          :data-source="history"
          :pagination="{ pageSize: 10 }"
          row-key="created_at"
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

    <!-- Create Entry Modal -->
    <a-modal
      v-model:open="showCreateModal"
      :title="t('metacognition.createEntry')"
      :confirm-loading="createMutation.loading.value"
      @ok="handleCreate"
      @cancel="resetForm"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('metacognition.type')" required>
          <a-select v-model:value="createForm.type" :placeholder="t('metacognition.selectType')">
            <a-select-option value="self_assessment">{{ t('metacognition.selfAssessment') }}</a-select-option>
            <a-select-option value="strategy">{{ t('metacognition.strategy') }}</a-select-option>
            <a-select-option value="monitoring">{{ t('metacognition.monitoring') }}</a-select-option>
            <a-select-option value="planning">{{ t('metacognition.planning') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('metacognition.content')" required>
          <a-textarea
            v-model:value="createForm.content"
            :rows="4"
            :placeholder="t('metacognition.contentPlaceholder')"
          />
        </a-form-item>
        <a-form-item :label="t('metacognition.context')">
          <a-input v-model:value="createForm.context" :placeholder="t('metacognition.contextPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('metacognition.confidence')">
          <a-slider v-model:value="createForm.confidence" :min="0" :max="1" :step="0.05" />
          <span class="confidence-display">{{ formatPercent(createForm.confidence) }}</span>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useMutation } from '@/composables/useAPI'
import * as metacognitionApi from '@/api/modules/metacognition'
import type {
  MetacognitionEntry,
  MetacognitionStats,
  MetacognitionCreatePayload,
  CognitiveLoadState,
  ReflectionHistoryItem,
  StructuredLesson,
} from '@/api/modules/metacognition'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage({
  onAgentChange: () => {
    refreshAll()
  },
})

// --- Stats / entries / load state / lessons / history ---
const stats = ref<MetacognitionStats | null>(null)
const loadState = ref<CognitiveLoadState | null>(null)
const history = ref<ReflectionHistoryItem[]>([])
const lessons = ref<StructuredLesson[]>([])
const lessonsLoading = ref(false)
const reflecting = ref(false)
const loading = ref(false)

const entryItems = ref<MetacognitionEntry[]>([])
const entryTotal = ref(0)
const entryPage = ref(1)
const entrySize = ref(10)
const entriesLoading = ref(false)
const typeFilter = ref<string | undefined>(undefined)

const showCreateModal = ref(false)
const createForm = reactive<{
  type: string
  content: string
  context: string
  confidence: number
}>({
  type: 'self_assessment',
  content: '',
  context: '',
  confidence: 0.5,
})

const createMutation = useMutation<MetacognitionCreatePayload, MetacognitionEntry>(
  (data) => metacognitionApi.createMetacognition(agentId.value, data),
)

const typeColorMap: Record<string, string> = {
  self_assessment: 'blue',
  strategy: 'purple',
  monitoring: 'green',
  planning: 'orange',
}

const operatorColor = (op: string) =>
  ({
    drift: 'red',
    contrast: 'orange',
    sequence: 'volcano',
    calibration: 'purple',
    budget: 'gold',
  })[op] || 'default'

const formatPercent = (val: number | undefined | null) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const formatType = (type: string) => {
  const map: Record<string, string> = {
    self_assessment: t('metacognition.selfAssessment'),
    strategy: t('metacognition.strategy'),
    monitoring: t('metacognition.monitoring'),
    planning: t('metacognition.planning'),
  }
  return map[type] || type
}

const formatTime = (ts: string | null) => (ts ? new Date(ts).toLocaleString() : '')
const formatDate = (d: string) => {
  if (!d) return ''
  const date = new Date(d)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

const trendBarHeight = (count: number) => {
  if (!stats.value?.recent_trend?.length) return 0
  const max = Math.max(...stats.value.recent_trend.map((p) => p.count), 1)
  return Math.max(4, (count / max) * 80)
}

// --- Cognitive load metrics (real state) ---
const metrics = computed(() => {
  if (!loadState.value) return []
  const s = loadState.value
  return [
    {
      label: t('metacognition.loadScore'),
      displayValue: formatPercent(s.load_score),
      percent: Math.round((s.load_score || 0) * 100),
      color: '#6366f1',
      status: (s.load_score || 0) >= 0.7 ? t('metacognition.high') : t('metacognition.low'),
    },
    {
      label: t('metacognition.errorRate'),
      displayValue: formatPercent(s.error_rate),
      percent: Math.round((s.error_rate || 0) * 100),
      color: '#f59e0b',
      status: (s.error_rate || 0) <= 0.3 ? t('metacognition.low') : t('metacognition.high'),
    },
    {
      label: t('metacognition.activeTasks'),
      displayValue: String(s.active_tasks ?? 0),
      percent: Math.min(100, Math.round(((s.active_tasks || 0) / 10) * 100)),
      color: '#8b5cf6',
      status: (s.active_tasks || 0) > 0 ? t('metacognition.active') : t('metacognition.idle'),
    },
    {
      label: t('metacognition.responseTime'),
      displayValue: `${Math.round(s.response_time_ms || 0)} ms`,
      percent: Math.min(100, Math.round(((s.response_time_ms || 0) / 5000) * 100)),
      color: '#10b981',
      status: (s.response_time_ms || 0) < 5000 ? t('metacognition.normal') : t('metacognition.slow'),
    },
  ]
})

// --- Load factor composition (B 公式四因子) ---
const factors = computed(() => {
  const f = loadState.value?.factors
  if (!f) return []
  const labelMap: Record<string, string> = {
    tasks: t('metacognition.factorTasks'),
    memory: t('metacognition.factorMemory'),
    response: t('metacognition.factorResponse'),
    error: t('metacognition.factorError'),
  }
  return Object.entries(f).map(([name, value]) => ({ name: labelMap[name] || name, value: value as number }))
})

const loadBadge = computed(() => {
  const level = loadState.value?.load_level
  if (level === 'low' || level === 'moderate') return 'success'
  if (level === 'high') return 'warning'
  if (level === 'overload') return 'error'
  return 'default'
})

const historyColumns = computed(() => [
  { title: t('common.createdAt'), dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: t('metacognition.confidence'), key: 'confidence', width: 120 },
  { title: t('metacognition.trigger'), key: 'trigger', width: 120 },
  { title: t('common.description'), dataIndex: 'summary', key: 'summary', ellipsis: true },
])

// --- Fetchers ---
const fetchState = async () => {
  try {
    const res = await metacognitionApi.getCognitiveState(agentId.value)
    loadState.value = res?.data ?? null
  } catch {
    loadState.value = null
  }
}

const fetchStats = async () => {
  try {
    const res = await metacognitionApi.getMetacognitionStats(agentId.value)
    stats.value = res?.data ?? null
  } catch {
    stats.value = null
  }
}

const fetchEntries = async () => {
  entriesLoading.value = true
  try {
    const params: { page: number; size: number; type?: string } = {
      page: entryPage.value,
      size: entrySize.value,
    }
    if (typeFilter.value) params.type = typeFilter.value
    const res = await metacognitionApi.getMetacognitionEntries(agentId.value, params)
    const data = res?.data
    if (data && typeof data === 'object' && 'items' in data) {
      entryItems.value = data.items || []
      entryTotal.value = data.total || 0
    } else {
      entryItems.value = []
      entryTotal.value = 0
    }
  } catch {
    entryItems.value = []
    entryTotal.value = 0
  } finally {
    entriesLoading.value = false
  }
}

const fetchLessons = async () => {
  lessonsLoading.value = true
  try {
    const res = await metacognitionApi.getLessons(agentId.value)
    lessons.value = res?.data?.items ?? []
  } catch {
    lessons.value = []
  } finally {
    lessonsLoading.value = false
  }
}

const fetchHistory = async () => {
  try {
    const res = await metacognitionApi.getReflectionHistory(agentId.value)
    history.value = res?.data?.items ?? []
  } catch {
    history.value = []
  }
}

const onTypeFilterChange = () => {
  entryPage.value = 1
  fetchEntries()
}

const onEntryPageChange = (page: number) => {
  entryPage.value = page
  fetchEntries()
}

const handleCreate = async () => {
  if (!createForm.content.trim()) {
    message.warning(t('metacognition.contentRequired'))
    return
  }
  const payload: MetacognitionCreatePayload = {
    type: createForm.type,
    content: createForm.content,
    context: createForm.context || undefined,
    confidence: createForm.confidence,
  }
  const result = await createMutation.execute(payload)
  if (result) {
    message.success(t('common.success'))
    showCreateModal.value = false
    resetForm()
    await Promise.all([fetchEntries(), fetchStats()])
  } else if (createMutation.error.value) {
    message.error(createMutation.error.value)
  }
}

const handleReflect = async () => {
  reflecting.value = true
  try {
    const res = await metacognitionApi.triggerReflection(agentId.value)
    const report = res?.data
    if (report?.lessons?.length) {
      message.success(t('metacognition.reflectDoneWith', { n: report.lessons.length }))
    } else {
      message.info(t('metacognition.reflectDoneClean'))
    }
    await Promise.all([fetchLessons(), fetchHistory()])
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    reflecting.value = false
  }
}

const resetForm = () => {
  createForm.type = 'self_assessment'
  createForm.content = ''
  createForm.context = ''
  createForm.confidence = 0.5
}

const refreshAll = () => {
  loading.value = true
  Promise.all([fetchState(), fetchStats(), fetchEntries(), fetchLessons(), fetchHistory()]).finally(
    () => {
      loading.value = false
    },
  )
}

onMounted(() => {
  refreshAll()
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

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Stats dashboard */
.stats-dashboard {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 2px 0;
}

.stat-label {
  font-size: 11px;
  color: var(--nr-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.stat-value {
  font-family: var(--nr-font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--nr-text-primary);
}

/* Trend chart */
.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 100px;
  padding: 8px 0;
}

.trend-bar-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-width: 0;
  gap: 4px;
}

.trend-bar {
  width: 100%;
  max-width: 32px;
  background: linear-gradient(180deg, #6366f1, #8b5cf6);
  border-radius: 3px 3px 0 0;
  min-height: 4px;
  transition: height 0.3s ease;
}

.trend-label {
  font-size: 9px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}

/* Metrics grid */
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

/* Entries list */
.entries-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.entry-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--nr-border-secondary, rgba(255, 255, 255, 0.06));
  border-radius: 8px;
  background: var(--nr-bg-elevated, rgba(255, 255, 255, 0.02));
  transition: border-color 0.2s ease;
}

.entry-card:hover {
  border-color: var(--nr-border-hover, rgba(99, 102, 241, 0.3));
}

.entry-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.entry-date {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}

.entry-content {
  font-size: 13px;
  color: var(--nr-text-primary);
  margin: 0;
  line-height: 1.5;
}

.entry-context {
  font-size: 12px;
  color: var(--nr-text-secondary);
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 4px;
}

.context-label {
  font-weight: 500;
  color: var(--nr-text-tertiary);
}

.entry-footer {
  display: flex;
  align-items: center;
  gap: 12px;
}

.entry-confidence {
  display: flex;
  align-items: center;
  gap: 8px;
}

.confidence-label {
  font-size: 11px;
  color: var(--nr-text-secondary);
}

.confidence-display {
  font-size: 12px;
  color: var(--nr-text-secondary);
  font-family: var(--nr-font-mono);
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
