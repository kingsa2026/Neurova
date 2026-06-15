<template>
  <div class="reflection-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('growth.reflection') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="secondary" size="sm" :loading="loading" @click="fetchReflections">
          {{ t('common.refresh') }}
        </GlassButton>
        <GlassButton variant="primary" @click="showCreateModal = true">
          {{ t('common.create') }}
        </GlassButton>
      </div>
    </div>

    <!-- Stats -->
    <div class="stats-grid">
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ total }}</div>
          <div class="stat-label">{{ t('common.total') }}</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ averageQuality }}</div>
          <div class="stat-label">{{ t('growth.avgQuality') }}</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ categoryBreakdown.length }}</div>
          <div class="stat-label">{{ t('common.type') + 's' }}</div>
        </div>
      </GlassCard>
    </div>

    <!-- Reflections list -->
    <GlassCard>
      <div class="toolbar">
        <a-input-search
          v-model:value="searchQuery"
          :placeholder="t('common.search')"
          style="max-width: 320px"
          allow-clear
          @search="fetchReflections"
        />
        <a-select
          v-model:value="categoryFilter"
          :placeholder="t('common.type')"
          allow-clear
          style="min-width: 160px"
          @change="fetchReflections"
        >
          <a-select-option value="general">{{ t('growth.general') }}</a-select-option>
          <a-select-option value="insight">{{ t('growth.insight') }}</a-select-option>
          <a-select-option value="lesson">{{ t('growth.lesson') }}</a-select-option>
          <a-select-option value="mistake">{{ t('growth.mistake') }}</a-select-option>
        </a-select>
      </div>

      <a-spin :spinning="loading">
        <a-table
          :columns="tableColumns"
          :data-source="filteredReflections"
          :pagination="{
            current: page,
            pageSize: size,
            total: total,
            showSizeChanger: true,
            showTotal: (t: number) => `${t} items`,
          }"
          row-key="id"
          size="middle"
          @change="onTableChange"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'content'">
              <div class="content-preview">{{ truncate(record.content, 100) }}</div>
            </template>
            <template v-else-if="column.key === 'quality'">
              <div class="quality-cell">
                <a-rate :value="record.quality_score || record.quality || 0" disabled :count="5" style="font-size: 14px" />
                <span v-if="record.quality_score !== undefined" class="quality-score-text">
                  {{ record.quality_score.toFixed(1) }}
                </span>
              </div>
            </template>
            <template v-else-if="column.key === 'type'">
              <a-tag :color="categoryColor(record.category || record.type)">{{ record.category || record.type || 'general' }}</a-tag>
            </template>
            <template v-else-if="column.key === 'insights'">
              <span v-if="record.insights?.length" class="insights-count">
                {{ record.insights.length }}
              </span>
              <span v-else class="no-insights">-</span>
            </template>
            <template v-else-if="column.key === 'actions'">
              <div class="row-actions">
                <GlassButton size="sm" variant="ghost" @click="viewReflection(record)">
                  {{ t('common.open') }}
                </GlassButton>
              </div>
            </template>
          </template>
        </a-table>
      </a-spin>
    </GlassCard>

    <!-- Create reflection modal -->
    <a-modal
      v-model:open="showCreateModal"
      :title="t('growth.reflection')"
      :confirm-loading="creating"
      @ok="createReflection"
      width="560px"
    >
      <a-form layout="vertical" :model="createForm">
        <a-form-item :label="t('common.description')" required>
          <a-textarea v-model:value="createForm.content" :rows="5" :placeholder="t('growth.reflection')" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item :label="t('common.type')">
              <a-select v-model:value="createForm.category" style="width: 100%">
                <a-select-option value="general">{{ t('growth.general') }}</a-select-option>
                <a-select-option value="insight">{{ t('growth.insight') }}</a-select-option>
                <a-select-option value="lesson">{{ t('growth.lesson') }}</a-select-option>
                <a-select-option value="mistake">{{ t('growth.mistake') }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item :label="t('growth.quality')">
              <a-rate v-model:value="createForm.quality" :count="5" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item :label="t('growth.insights')">
          <a-textarea v-model:value="createForm.insights" :rows="3" :placeholder="t('reflection.keyTakeaways')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Detail modal -->
    <a-modal
      v-model:open="showDetailModal"
      :title="t('growth.reflection')"
      :footer="null"
      width="640px"
    >
      <template v-if="selectedReflection">
        <div class="detail-section">
          <div class="detail-label">{{ t('common.description') }}</div>
          <div class="detail-content">{{ selectedReflection.content }}</div>
        </div>
        <div class="detail-section">
          <div class="detail-label">{{ t('common.type') }}</div>
          <a-tag :color="categoryColor(selectedReflection.category || selectedReflection.type)">{{ selectedReflection.category || selectedReflection.type || 'general' }}</a-tag>
        </div>
        <div class="detail-section">
          <div class="detail-label">{{ t('growth.quality') }}</div>
          <a-rate :value="selectedReflection.quality_score || selectedReflection.quality || 0" disabled :count="5" />
          <span v-if="selectedReflection.quality_score !== undefined" class="quality-score-detail">
            {{ selectedReflection.quality_score.toFixed(1) }} / 5
          </span>
        </div>
        <div v-if="selectedReflection.insights?.length || selectedReflection.insights" class="detail-section">
          <div class="detail-label">{{ t('growth.insights') }}</div>
          <div v-if="Array.isArray(selectedReflection.insights)" class="detail-insights-list">
            <ul>
              <li v-for="(insight, idx) in selectedReflection.insights" :key="idx">{{ insight }}</li>
            </ul>
          </div>
          <div v-else class="detail-content">{{ selectedReflection.insights }}</div>
        </div>
        <div class="detail-section">
          <div class="detail-label">{{ t('common.createdAt') }}</div>
          <div class="detail-content mono">{{ selectedReflection.created_at }}</div>
        </div>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import * as growthApi from '@/api/modules/growth'
import type { GrowthReflection } from '@/api/modules/growth'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage({
  onAgentChange: () => {
    fetchReflections()
  },
})

const loading = ref(false)
const creating = ref(false)
const reflections = ref<GrowthReflection[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(12)
const searchQuery = ref('')
const categoryFilter = ref<string | undefined>(undefined)
const showCreateModal = ref(false)
const showDetailModal = ref(false)
const selectedReflection = ref<any>(null)

const createForm = ref({
  content: '',
  category: 'general',
  quality: 3,
  insights: '',
})

const tableColumns = computed(() => [
  { title: t('common.description'), key: 'content', dataIndex: 'content', ellipsis: true },
  { title: t('common.type'), key: 'type', width: 120 },
  { title: t('reflection.quality'), key: 'quality', width: 180 },
  { title: t('growth.insights'), key: 'insights', width: 90, align: 'center' as const },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
  { title: t('common.actions'), key: 'actions', width: 120 },
])

const categoryColor = (cat: string) => {
  const map: Record<string, string> = {
    general: 'blue', insight: 'purple', lesson: 'green', mistake: 'red',
  }
  return map[cat] || 'default'
}

const filteredReflections = computed(() => {
  if (!searchQuery.value) return reflections.value
  const q = searchQuery.value.toLowerCase()
  return reflections.value.filter(
    (r) =>
      (r.content || '').toLowerCase().includes(q) ||
      (r.category || '').toLowerCase().includes(q),
  )
})

const averageQuality = computed(() => {
  const withScore = reflections.value.filter((r) => r.quality_score !== undefined)
  if (withScore.length === 0) return '0'
  const sum = withScore.reduce((acc, r) => acc + (r.quality_score || 0), 0)
  return (sum / withScore.length).toFixed(1)
})

const categoryBreakdown = computed(() => {
  const cats = new Set(reflections.value.map((r) => r.category).filter(Boolean))
  return [...cats]
})

const truncate = (text: string, len: number) =>
  text && text.length > len ? text.slice(0, len) + '...' : text || ''

const onTableChange = (pagination: any) => {
  page.value = pagination.current || 1
  size.value = pagination.pageSize || 12
  fetchReflections()
}

const fetchReflections = async () => {
  loading.value = true
  try {
    const res = await growthApi.getReflections(agentId.value, {
      page: page.value,
      size: size.value,
    })
    const data = res.data
    if (data && typeof data === 'object' && 'items' in data) {
      reflections.value = data.items ?? []
      total.value = data.total ?? 0
    } else {
      reflections.value = Array.isArray(data) ? data : []
      total.value = reflections.value.length
    }
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const createReflection = async () => {
  if (!createForm.value.content.trim()) {
    message.warning(t('validation.required'))
    return
  }
  creating.value = true
  try {
    await growthApi.createReflection(
      agentId.value,
      createForm.value.content,
      createForm.value.category,
    )
    message.success(t('common.success'))
    showCreateModal.value = false
    createForm.value = { content: '', category: 'general', quality: 3, insights: '' }
    await fetchReflections()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    creating.value = false
  }
}

const viewReflection = (record: any) => {
  selectedReflection.value = record
  showDetailModal.value = true
}

onMounted(() => {
  fetchReflections()
})
</script>

<style scoped>
.reflection-page {
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
  gap: 12px;
  margin-bottom: 16px;
}

.content-preview {
  font-size: 13px;
  color: var(--nr-text-primary);
  line-height: 1.5;
}

.quality-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.quality-score-text {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
}

.quality-score-detail {
  font-size: 13px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
  margin-left: 8px;
}

.insights-count {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
  background: rgba(99, 102, 241, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
}

.no-insights {
  font-size: 12px;
  color: var(--nr-text-muted);
}

.row-actions {
  display: flex;
  gap: 8px;
}

.detail-section {
  margin-bottom: 16px;
}

.detail-label {
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}

.detail-content {
  font-size: 14px;
  color: var(--nr-text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
}

.detail-insights-list ul {
  margin: 0;
  padding-left: 18px;
}

.detail-insights-list li {
  font-size: 14px;
  color: var(--nr-text-primary);
  line-height: 1.6;
}

.mono {
  font-family: var(--nr-font-mono);
  font-size: 12px;
}
</style>
