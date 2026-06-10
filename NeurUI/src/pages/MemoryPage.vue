<template>
  <div class="memory-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('memory.title') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
        <div class="isolation-context">
          <a-tag color="blue" class="iso-tag">
            <span class="iso-label">Isolation:</span>
            agent_id: {{ isolationKey || 'none' }}
          </a-tag>
          <a-tag color="cyan" class="iso-tag">
            <span class="iso-label">Level:</span>
            agent-scoped
          </a-tag>
        </div>
      </div>
      <GlassButton variant="primary" @click="showCreateModal = true">
        {{ t('memory.create') }}
      </GlassButton>
    </div>

    <!-- Stats overview -->
    <div class="stats-grid">
      <GlassCard v-for="stat in statsCards" :key="stat.label" variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ stat.value }}</div>
          <div class="stat-label">{{ stat.label }}</div>
        </div>
      </GlassCard>
    </div>

    <!-- Tabs & filters -->
    <GlassCard>
      <a-tabs v-model:activeKey="activeTab" @change="fetchMemories">
        <a-tab-pane key="all" :tab="t('common.all')" />
        <a-tab-pane key="working" :tab="t('memory.workingMemory')" />
        <a-tab-pane key="long_term" :tab="t('memory.longTerm')" />
        <a-tab-pane key="emotion" :tab="t('memory.emotion')" />
      </a-tabs>

      <div class="toolbar">
        <a-input-search
          v-model:value="searchQuery"
          :placeholder="t('memory.search')"
          style="max-width: 320px"
          allow-clear
          @search="fetchMemories"
        />
        <a-select
          v-model:value="categoryFilter"
          :placeholder="t('memory.categories')"
          allow-clear
          style="min-width: 160px"
          @change="fetchMemories"
        >
          <a-select-option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</a-select-option>
        </a-select>
      </div>
    </GlassCard>

    <!-- Memory table -->
    <GlassCard>
      <a-table
        :columns="tableColumns"
        :data-source="memories"
        :loading="loading"
        :pagination="{ pageSize: 15, showSizeChanger: true }"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'content'">
            <div class="content-preview">
              {{ truncate(record.content, 120) }}
              <a-tag v-if="record.shared || (record.share_group_ids && record.share_group_ids.length > 0)" color="gold" class="shared-badge">
                Shared
              </a-tag>
            </div>
          </template>
          <template v-else-if="column.key === 'category'">
            <a-tag>{{ record.category }}</a-tag>
          </template>
          <template v-else-if="column.key === 'importance'">
            <a-progress
              :percent="Math.round((record.importance || 0) * 100)"
              :stroke-color="importanceColor(record.importance)"
              size="small"
              :show-info="false"
              style="width: 80px"
            />
          </template>
          <template v-else-if="column.key === 'actions'">
            <div class="row-actions">
              <GlassButton size="sm" variant="ghost" @click="viewMemory(record)">
                {{ t('common.open') }}
              </GlassButton>
              <a-popconfirm
                :title="t('memory.forget') + '?'"
                @confirm="deleteMemory(record.id)"
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
    </GlassCard>

    <!-- Create memory modal -->
    <a-modal
      v-model:open="showCreateModal"
      :title="t('memory.create')"
      :confirm-loading="creating"
      @ok="createMemory"
    >
      <a-form layout="vertical" :model="createForm">
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="createForm.content" :rows="4" />
        </a-form-item>
        <a-form-item :label="t('memory.categories')">
          <a-select v-model:value="createForm.category" :placeholder="t('memory.categories')">
            <a-select-option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="Importance (0-1)">
          <a-slider v-model:value="createForm.importance" :min="0" :max="1" :step="0.1" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- View/Edit memory modal -->
    <a-modal
      v-model:open="showDetailModal"
      :title="t('memory.overview')"
      :footer="null"
      width="640px"
    >
      <template v-if="selectedMemory">
        <a-form layout="vertical">
          <a-form-item :label="t('common.description')">
            <a-textarea v-model:value="selectedMemory.content" :rows="6" :readonly="!editing" />
          </a-form-item>
          <a-form-item :label="t('memory.categories')">
            <a-tag>{{ selectedMemory.category }}</a-tag>
          </a-form-item>
          <a-form-item label="Importance">
            <a-progress :percent="Math.round((selectedMemory.importance || 0) * 100)" size="small" />
          </a-form-item>
          <a-form-item :label="t('common.createdAt')">
            {{ selectedMemory.created_at }}
          </a-form-item>
        </a-form>
        <div class="modal-actions">
          <GlassButton variant="ghost" size="sm" @click="editing = !editing">
            {{ editing ? t('common.cancel') : t('common.edit') }}
          </GlassButton>
          <GlassButton v-if="editing" variant="primary" size="sm" :loading="updating" @click="updateMemory">
            {{ t('common.save') }}
          </GlassButton>
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
import { useAgentStore } from '@/stores/agents'
import { request } from '@/api'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()
const agentStore = useAgentStore()

// Expose the agent_id portion of the three-level isolation key
const isolationKey = computed(() => agentStore.currentIsolationKey)

const loading = ref(false)
const creating = ref(false)
const updating = ref(false)
const editing = ref(false)
const memories = ref<any[]>([])
const activeTab = ref('all')
const searchQuery = ref('')
const categoryFilter = ref<string | undefined>(undefined)
const showCreateModal = ref(false)
const showDetailModal = ref(false)
const selectedMemory = ref<any>(null)

const categories = ['general', 'conversation', 'fact', 'preference', 'skill', 'emotion']

const createForm = ref({
  content: '',
  category: 'general',
  importance: 0.5,
})

const statsCards = computed(() => [
  { label: t('common.total'), value: memories.value.length },
  { label: t('memory.workingMemory'), value: memories.value.filter((m) => m.memory_type === 'working').length },
  { label: t('memory.longTerm'), value: memories.value.filter((m) => m.memory_type === 'long_term').length },
  { label: t('memory.emotion'), value: memories.value.filter((m) => m.memory_type === 'emotion').length },
])

const tableColumns = computed(() => [
  { title: t('common.description'), key: 'content', dataIndex: 'content', ellipsis: true },
  { title: t('memory.categories'), key: 'category', width: 120 },
  { title: 'Importance', key: 'importance', width: 120 },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
  { title: t('common.actions'), key: 'actions', width: 180 },
])

const truncate = (text: string, len: number) =>
  text && text.length > len ? text.slice(0, len) + '...' : text || ''

const importanceColor = (val: number) => {
  if (val >= 0.8) return '#10b981'
  if (val >= 0.5) return '#6366f1'
  return '#f59e0b'
}

const fetchMemories = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = { agent_id: agentId.value }
    if (activeTab.value !== 'all') params.memory_type = activeTab.value
    if (searchQuery.value) params.q = searchQuery.value
    if (categoryFilter.value) params.category = categoryFilter.value
    const res: any = await request.get('/memory', { params })
    const data = res?.data ?? res
    memories.value = Array.isArray(data) ? data : data?.items ?? data?.memories ?? []
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const createMemory = async () => {
  if (!createForm.value.content.trim()) {
    message.warning(t('validation.required'))
    return
  }
  creating.value = true
  try {
    await request.post('/memory', {
      agent_id: agentId.value,
      content: createForm.value.content,
      category: createForm.value.category,
      importance: createForm.value.importance,
    })
    message.success(t('common.success'))
    showCreateModal.value = false
    createForm.value = { content: '', category: 'general', importance: 0.5 }
    await fetchMemories()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    creating.value = false
  }
}

const viewMemory = (record: any) => {
  selectedMemory.value = { ...record }
  editing.value = false
  showDetailModal.value = true
}

const updateMemory = async () => {
  if (!selectedMemory.value) return
  updating.value = true
  try {
    await request.put(`/memory/${selectedMemory.value.id}`, {
      content: selectedMemory.value.content,
    })
    message.success(t('common.success'))
    editing.value = false
    await fetchMemories()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    updating.value = false
  }
}

const deleteMemory = async (id: string) => {
  try {
    await request.delete(`/memory/${id}`)
    message.success(t('common.success'))
    await fetchMemories()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  }
}

onMounted(() => {
  fetchMemories()
})
</script>

<style scoped>
.memory-page {
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

.isolation-context {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.iso-tag {
  font-family: var(--nr-font-mono);
  font-size: 11px;
}

.iso-label {
  font-weight: 600;
}

.shared-badge {
  font-size: 10px;
  margin-left: 6px;
  vertical-align: middle;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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
  margin-top: 16px;
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

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--nr-glass-border);
}
</style>
