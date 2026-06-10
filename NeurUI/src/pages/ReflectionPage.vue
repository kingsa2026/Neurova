<template>
  <div class="reflection-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('growth.reflection') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <GlassButton variant="primary" @click="showCreateModal = true">
        {{ t('common.create') }}
      </GlassButton>
    </div>

    <!-- Stats -->
    <div class="stats-grid">
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ reflections.length }}</div>
          <div class="stat-label">{{ t('common.total') }}</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ averageQuality }}</div>
          <div class="stat-label">Avg Quality</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ recentCount }}</div>
          <div class="stat-label">Last 7 Days</div>
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
        />
      </div>

      <a-spin :spinning="loading">
        <a-table
          :columns="tableColumns"
          :data-source="filteredReflections"
          :pagination="{ pageSize: 12, showSizeChanger: true }"
          row-key="id"
          size="middle"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'content'">
              <div class="content-preview">{{ truncate(record.content, 100) }}</div>
            </template>
            <template v-else-if="column.key === 'quality'">
              <a-rate :value="record.quality || 0" disabled :count="5" style="font-size: 14px" />
            </template>
            <template v-else-if="column.key === 'type'">
              <a-tag :color="record.type === 'insight' ? 'purple' : record.type === 'lesson' ? 'green' : 'blue'">
                {{ record.type || 'general' }}
              </a-tag>
            </template>
            <template v-else-if="column.key === 'actions'">
              <div class="row-actions">
                <GlassButton size="sm" variant="ghost" @click="viewReflection(record)">
                  {{ t('common.open') }}
                </GlassButton>
                <a-popconfirm
                  :title="t('common.delete') + '?'"
                  @confirm="deleteReflection(record.id)"
                  :ok-text="t('common.yes')"
                  :cancel-text="t('common.no')"
                >
                  <GlassButton size="sm" variant="danger">
                    {{ t('common.delete') }}
                  </GlassButton>
                </a-popconfirm>
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
              <a-select v-model:value="createForm.type" style="width: 100%">
                <a-select-option value="general">General</a-select-option>
                <a-select-option value="insight">Insight</a-select-option>
                <a-select-option value="lesson">Lesson</a-select-option>
                <a-select-option value="mistake">Mistake</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="Quality">
              <a-rate v-model:value="createForm.quality" :count="5" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="Insights">
          <a-textarea v-model:value="createForm.insights" :rows="3" placeholder="Key takeaways..." />
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
          <a-tag>{{ selectedReflection.type || 'general' }}</a-tag>
        </div>
        <div class="detail-section">
          <div class="detail-label">Quality</div>
          <a-rate :value="selectedReflection.quality || 0" disabled :count="5" />
        </div>
        <div v-if="selectedReflection.insights" class="detail-section">
          <div class="detail-label">Insights</div>
          <div class="detail-content">{{ selectedReflection.insights }}</div>
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
import { request } from '@/api'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()

const loading = ref(false)
const creating = ref(false)
const reflections = ref<any[]>([])
const searchQuery = ref('')
const showCreateModal = ref(false)
const showDetailModal = ref(false)
const selectedReflection = ref<any>(null)

const createForm = ref({
  content: '',
  type: 'general',
  quality: 3,
  insights: '',
})

const tableColumns = computed(() => [
  { title: t('common.description'), key: 'content', dataIndex: 'content', ellipsis: true },
  { title: t('common.type'), key: 'type', width: 120 },
  { title: 'Quality', key: 'quality', width: 160 },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
  { title: t('common.actions'), key: 'actions', width: 180 },
])

const filteredReflections = computed(() => {
  if (!searchQuery.value) return reflections.value
  const q = searchQuery.value.toLowerCase()
  return reflections.value.filter(
    (r) =>
      (r.content || '').toLowerCase().includes(q) ||
      (r.type || '').toLowerCase().includes(q),
  )
})

const averageQuality = computed(() => {
  if (reflections.value.length === 0) return '0'
  const sum = reflections.value.reduce((acc, r) => acc + (r.quality || 0), 0)
  return (sum / reflections.value.length).toFixed(1)
})

const recentCount = computed(() => {
  const weekAgo = new Date()
  weekAgo.setDate(weekAgo.getDate() - 7)
  return reflections.value.filter((r) => new Date(r.created_at) >= weekAgo).length
})

const truncate = (text: string, len: number) =>
  text && text.length > len ? text.slice(0, len) + '...' : text || ''

const fetchReflections = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/growth/reflection', {
      params: { agent_id: agentId.value },
    })
    const data = res?.data ?? res
    reflections.value = Array.isArray(data) ? data : data?.items ?? data?.reflections ?? []
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
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
    await request.post('/growth/reflection', {
      agent_id: agentId.value,
      content: createForm.value.content,
      type: createForm.value.type,
      quality: createForm.value.quality,
      insights: createForm.value.insights,
    })
    message.success(t('common.success'))
    showCreateModal.value = false
    createForm.value = { content: '', type: 'general', quality: 3, insights: '' }
    await fetchReflections()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    creating.value = false
  }
}

const viewReflection = (record: any) => {
  selectedReflection.value = record
  showDetailModal.value = true
}

const deleteReflection = async (id: string) => {
  try {
    await request.delete(`/growth/reflection/${id}`)
    message.success(t('common.success'))
    await fetchReflections()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  }
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
  margin-bottom: 16px;
}

.content-preview {
  font-size: 13px;
  color: var(--nr-text-primary);
  line-height: 1.5;
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

.mono {
  font-family: var(--nr-font-mono);
  font-size: 12px;
}
</style>
