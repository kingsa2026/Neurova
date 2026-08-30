<template>
  <div class="memory-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('memory.title') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
        <div class="isolation-context">
          <a-tag color="blue" class="iso-tag">
            <span class="iso-label">{{ t('memory.isolation') }}</span>
            agent_id: {{ isolationKey || 'none' }}
          </a-tag>
          <a-tag color="cyan" class="iso-tag">
            <span class="iso-label">{{ t('memory.level') }}</span>
            {{ t('memory.agentScoped') }}
          </a-tag>
        </div>
      </div>
      <div class="header-actions">
        <a-tooltip :title="t('memory.decay')">
          <GlassButton variant="ghost" size="sm" :loading="decaying" @click="handleTriggerDecay">
            {{ t('memory.decay') }}
          </GlassButton>
        </a-tooltip>
        <GlassButton variant="secondary" size="sm" :loading="loading" @click="fetchMemories">
          {{ t('common.refresh') }}
        </GlassButton>
        <a-dropdown>
          <GlassButton variant="secondary" size="sm">
            ⋯
          </GlassButton>
          <template #overlay>
            <a-menu>
              <a-menu-item @click="handleExport">
                {{ t('memory.exportMem') }}
              </a-menu-item>
              <a-menu-item @click="showImportModal = true">
                {{ t('memory.importMem') }}
              </a-menu-item>
              <a-menu-divider />
              <a-menu-item @click="$router.push('/memory/settings')">
                {{ t('memorySettings.title') }}
              </a-menu-item>
              <a-menu-item @click="$router.push('/memory/search-settings')">
                {{ t('memorySearch.title') }}
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <GlassButton variant="primary" @click="showCreateModal = true">
          {{ t('memory.create') }}
        </GlassButton>
      </div>
    </div>

    <!-- Stats overview (from getMemoryStats API) -->
    <a-spin :spinning="loadingStats">
      <div class="stats-grid">
        <GlassCard v-for="stat in statsCards" :key="stat.label" variant="subtle">
          <div class="stat-item">
            <div class="stat-value">{{ stat.value }}</div>
            <div class="stat-label">{{ stat.label }}</div>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- By-type breakdown (NEW - from stats API) -->
    <div v-if="memoryStats?.by_type?.length" class="type-breakdown">
      <GlassCard variant="subtle">
        <div class="breakdown-header">{{ t('memory.overview') }}</div>
        <div class="breakdown-grid">
          <div v-for="bt in memoryStats.by_type" :key="bt.type" class="breakdown-item">
            <a-progress
              type="circle"
              :percent="Math.round((bt.count / (memoryStats.total_memories || 1)) * 100)"
              :size="48"
              :stroke-color="typeColor(bt.type)"
            />
            <div class="breakdown-label">{{ bt.type }}</div>
            <div class="breakdown-count">{{ bt.count }}</div>
          </div>
        </div>
      </GlassCard>
    </div>

    <!-- Tabs & filters -->
    <GlassCard>
      <a-tabs v-model:activeKey="activeTab" @change="onTabChange">
        <a-tab-pane key="all" :tab="t('common.all')" />
        <a-tab-pane key="short_term" :tab="t('memory.workingMemory')" />
        <a-tab-pane key="long_term" :tab="t('memory.longTerm')" />
        <a-tab-pane key="episodic">
          <template #tab><span>Episodic</span></template>
        </a-tab-pane>
        <a-tab-pane key="semantic">
          <template #tab><span>Semantic</span></template>
        </a-tab-pane>
        <a-tab-pane key="hot">
          <template #tab><span>🔥 Hot</span></template>
        </a-tab-pane>
        <a-tab-pane key="crystallized">
          <template #tab><span>💎 Crystallized</span></template>
        </a-tab-pane>
      </a-tabs>

      <div class="toolbar">
        <a-input-search
          v-model:value="searchQuery"
          :placeholder="t('memory.search')"
          style="max-width: 320px"
          allow-clear
          @search="onSearch"
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
        <a-checkbox v-model:checked="semanticSearch" class="semantic-toggle">
          {{ t('memory.semanticSearch') || 'Semantic Search' }}
        </a-checkbox>
        <a-button class="md-edit-btn" @click="openMarkdownEditor">
          {{ t('ui.mdViewEditShort') }}
        </a-button>
      </div>
    </GlassCard>

    <!-- Semantic search results (NEW) -->
    <GlassCard v-if="semanticSearch && searchResults.length > 0" :title="t('memory.search') + ' Results'">
      <div class="search-results">
        <div v-for="result in searchResults" :key="result.id" class="search-result-item">
          <div class="result-header">
            <a-tag :color="typeColor(result.type)">{{ result.type }}</a-tag>
            <span class="result-score">Score: {{ Math.round(result.score * 100) }}%</span>
            <a-tag v-if="result.channel_scores" color="cyan" size="small">{{ t('memorySearch.nerfTag') }}</a-tag>
          </div>
          <div class="result-content">{{ result.content }}</div>
          <!-- NeRF channel scores breakdown -->
          <div v-if="result.channel_scores && Object.keys(result.channel_scores).length > 0" class="channel-scores-bar">
            <div
              v-for="(val, ch) in result.channel_scores"
              :key="ch"
              class="channel-segment"
              :style="{ width: `${(val as number) / result.score * 100}%`, backgroundColor: channelColorMap[ch as string] }"
              :title="`${ch}: ${(val as number).toFixed(3)}`"
            >
              <span v-if="(val as number) / result.score > 0.15" class="channel-label">{{ ch }}</span>
            </div>
          </div>
          <div class="result-date">{{ formatTime(result.created_at) }}</div>
        </div>
      </div>
    </GlassCard>

    <!-- Memory table -->
    <GlassCard v-if="memories.length > 0 || loading">
      <a-table
        :columns="tableColumns"
        :data-source="memories"
        :loading="loading"
        :locale="{ emptyText: '' }"
        :pagination="{
          current: page,
          pageSize: size,
          total: total,
          showSizeChanger: true,
          showTotal: (total: number) => `${total} items`,
        }"
        row-key="id"
        size="middle"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'content'">
            <div class="content-preview">
              {{ truncate(record.content, 120) }}
              <a-tag v-if="record.tags?.length" color="gold" class="shared-badge">
                {{ record.tags.join(', ') }}
              </a-tag>
            </div>
          </template>
          <template v-else-if="column.key === 'type'">
            <a-tag :color="typeColor(record.type)">{{ record.type }}</a-tag>
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
              <a-tooltip :title="t('memory.strengthen')">
                <GlassButton size="sm" variant="ghost" @click="handleStrengthen(record.id)">
                  ↑
                </GlassButton>
              </a-tooltip>
              <a-tooltip :title="t('memory.forget')">
                <GlassButton size="sm" variant="ghost" @click="handleForget(record.id)">
                  ↓
                </GlassButton>
              </a-tooltip>
              <a-popconfirm
                :title="t('memory.forget') + '?'"
                @confirm="confirmDeleteMemory(record.id)"
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
    <GlassCard v-else>
      <a-empty :description="t('common.noData')" />
    </GlassCard>

    <!-- Create memory modal -->
    <a-modal
      v-model:open="showCreateModal"
      :title="t('memory.create')"
      :confirm-loading="creating"
      @ok="createMemory"
    >
      <a-form layout="vertical" :model="createForm" :rules="{ content: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.description')" required>
          <a-textarea v-model:value="createForm.content" :rows="4" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item :label="t('common.type')">
              <a-select v-model:value="createForm.type" style="width: 100%">
                <a-select-option value="short_term">Short Term</a-select-option>
                <a-select-option value="long_term">Long Term</a-select-option>
                <a-select-option value="episodic">Episodic</a-select-option>
                <a-select-option value="semantic">Semantic</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item :label="t('memory.importance') + ' (0-1)'">
              <a-slider v-model:value="createForm.importance" :min="0" :max="1" :step="0.1" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item :label="t('memory.categories')">
          <a-select v-model:value="createForm.category" :placeholder="t('memory.categories')">
            <a-select-option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="Tags">
          <a-select v-model:value="createForm.tags" mode="tags" :placeholder="'Add tags'" />
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
          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item :label="t('common.type')">
                <a-tag :color="typeColor(selectedMemory.type)">{{ selectedMemory.type }}</a-tag>
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item :label="t('memory.importance')">
                <a-progress :percent="Math.round((selectedMemory.importance || 0) * 100)" size="small" />
              </a-form-item>
            </a-col>
          </a-row>
          <a-form-item v-if="selectedMemory.tags?.length" label="Tags">
            <a-tag v-for="tag in selectedMemory.tags" :key="tag" color="blue">{{ tag }}</a-tag>
          </a-form-item>
          <a-form-item v-if="selectedMemory.metadata" label="Metadata">
            <pre class="metadata-json">{{ JSON.stringify(selectedMemory.metadata, null, 2) }}</pre>
          </a-form-item>
          <a-form-item :label="t('common.createdAt')">
            {{ selectedMemory.created_at }}
          </a-form-item>
          <a-form-item v-if="selectedMemory.expires_at" label="Expires">
            {{ selectedMemory.expires_at }}
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

    <!-- Import memories modal -->
    <a-modal
      v-model:open="showImportModal"
      :title="t('memory.importMem')"
      :confirm-loading="importing"
      @ok="handleImport"
    >
      <a-form layout="vertical">
        <a-form-item label="JSON Data">
          <a-textarea v-model:value="importJson" :rows="8" placeholder='[{"content": "...", "type": "long_term"}]' />
        </a-form-item>
        <a-form-item label="Merge Mode">
          <a-radio-group v-model:value="importMergeMode">
            <a-radio-button value="skip">Skip</a-radio-button>
            <a-radio-button value="overwrite">Overwrite</a-radio-button>
            <a-radio-button value="merge">Merge</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-upload :before-upload="onImportFile" :show-upload-list="false" accept=".json">
          <GlassButton variant="ghost" size="sm">{{ t('memory.importMem') }} (File)</GlassButton>
        </a-upload>
      </a-form>
    </a-modal>

    <!-- Markdown view/edit modal (P1 记忆可解释性) -->
    <a-modal
      v-model:open="mdModal.open"
      :title="t('ui.mdViewEdit')"
      width="860px"
      :confirm-loading="mdModal.saving"
      :ok-text="t('ui.saveChanges')"
      :cancel-text="t('common.close')"
      @ok="saveMarkdownEdits"
    >
      <div class="md-toolbar">
        <a-button size="small" :loading="mdModal.loading" @click="openMarkdownEditor">
          {{ t('ui.reExport') }}
        </a-button>
        <span class="md-hint">
          {{ t('ui.mdEditHint') }}
        </span>
      </div>
      <a-textarea
        v-model:value="mdModal.markdown"
        class="md-editor"
        :rows="22"
        :placeholder="t('ui.mdLoadingExport')"
      />
      <div v-if="mdModal.lastStats" class="md-stats">
        {{ t('ui.mdLastSave', { updated: mdModal.lastStats.updated, unchanged: mdModal.lastStats.unchanged, missing: mdModal.lastStats.missing, conflicts: mdModal.lastStats.conflicts ?? 0 }) }}
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useAgentStore } from '@/stores/agents'
import * as memoryApi from '@/api/modules/memory'
import type { MemoryEntry, MemorySearchResult, MemoryStats } from '@/api/modules/memory'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage({
  onAgentChange: () => {
    fetchMemories()
    fetchStats()
  },
})
const agentStore = useAgentStore()

// Expose the agent_id portion of the three-level isolation key
const isolationKey = computed(() => agentStore.currentIsolationKey)

const loading = ref(false)
const loadingStats = ref(false)
const creating = ref(false)
const updating = ref(false)
const editing = ref(false)
const decaying = ref(false)
const importing = ref(false)

const memories = ref<MemoryEntry[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(15)
const activeTab = ref('all')
const searchQuery = ref('')
const categoryFilter = ref<string | undefined>(undefined)
const semanticSearch = ref(false)

const showCreateModal = ref(false)
const showDetailModal = ref(false)
const showImportModal = ref(false)
const selectedMemory = ref<any>(null)
const importJson = ref('')
const importMergeMode = ref<'skip' | 'overwrite' | 'merge'>('skip')

// Markdown 查看/编辑（P1 记忆可解释性）
const mdModal = reactive({
  open: false,
  loading: false,
  saving: false,
  markdown: '',
  lastStats: null as { updated: number; unchanged: number; missing: number; conflicts?: number } | null,
})

/** 打开弹窗并导出当前 Agent 记忆为可读 Markdown */
async function openMarkdownEditor(): Promise<void> {
  mdModal.open = true
  mdModal.loading = true
  try {
    const resp: any = await memoryApi.exportMemoryMarkdown(agentId.value || undefined)
    const payload = resp?.data ?? resp
    mdModal.markdown = payload?.data?.markdown ?? ''
    if (!mdModal.markdown) message.warning(t('ui.noExportMemory'))
  } catch (e) {
    console.error('[MemoryPage] export markdown failed:', e)
    message.error(t('ui.exportFailed'))
  } finally {
    mdModal.loading = false
  }
}

/** 提交编辑后的 Markdown；后端版本化 diff 后仅写回文本层 */
async function saveMarkdownEdits(): Promise<void> {
  if (mdModal.saving) return
  mdModal.saving = true
  try {
    const resp: any = await memoryApi.importMemoryMarkdown(
      mdModal.markdown,
      agentId.value || undefined
    )
    const payload = resp?.data ?? resp
    mdModal.lastStats = payload?.data?.stats ?? null
    const stats = mdModal.lastStats
    if (stats && stats.updated > 0) {
      message.success(t('ui.updatedMemories', { count: stats.updated }))
      fetchMemories()
      fetchStats()
    } else if (stats && (stats.conflicts ?? 0) > 0) {
      message.warning(t('ui.conflictNotOverwritten', { count: stats.conflicts }))
    } else {
      message.info(t('ui.noChangesToApply'))
    }
  } catch (e) {
    console.error('[MemoryPage] import markdown failed:', e)
    message.error(t('ui.saveFailed'))
  } finally {
    mdModal.saving = false
  }
}

// Stats from API
const memoryStats = ref<MemoryStats | null>(null)

// Semantic search results
const searchResults = ref<MemorySearchResult[]>([])

const categories = ['general', 'conversation', 'fact', 'preference', 'skill', 'emotion']

const createForm = ref({
  content: '',
  type: 'short_term',
  category: 'general',
  importance: 0.5,
  tags: [] as string[],
})

const typeColor = (type: string) => {
  const map: Record<string, string> = {
    short_term: '#6366f1', long_term: '#10b981', episodic: '#f59e0b', semantic: '#8b5cf6',
  }
  return map[type] || '#6366f1'
}

// NeRF channel color map for visualization
const channelColorMap: Record<string, string> = {
  text: '#1890ff',
  temperature: '#ff7a45',
  category: '#722ed1',
  graph: '#13c2c2',
  emotion: '#eb2f96',
  voice: '#52c41a',
}

const statsCards = computed(() => [
  { label: t('common.total'), value: memoryStats.value?.total_memories ?? memories.value.length },
  {
    label: t('memory.importance'),
    value: memoryStats.value?.avg_importance !== undefined
      ? `${Math.round(memoryStats.value.avg_importance * 100)}%`
      : '-',
  },
  {
    label: 'Storage',
    value: memoryStats.value?.storage_used !== undefined
      ? `${(memoryStats.value.storage_used / 1024).toFixed(1)} KB`
      : '-',
  },
  {
    label: t('common.type') + 's',
    value: memoryStats.value?.by_type?.length ?? 0,
  },
])

const tableColumns = computed(() => [
  { title: t('common.description'), key: 'content', dataIndex: 'content', ellipsis: true },
  { title: t('common.type'), key: 'type', width: 120 },
  { title: t('memory.importance'), key: 'importance', width: 120 },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
  { title: t('common.actions'), key: 'actions', width: 240 },
])

const truncate = (text: string, len: number) =>
  text && text.length > len ? text.slice(0, len) + '...' : text || ''

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const importanceColor = (val: number) => {
  if (val >= 0.8) return '#10b981'
  if (val >= 0.5) return '#6366f1'
  return '#f59e0b'
}

const onTabChange = () => {
  page.value = 1
  if (activeTab.value === 'hot') {
    fetchHotMemories()
  } else if (activeTab.value === 'crystallized') {
    fetchCrystallizedMemories()
  } else {
    fetchMemories()
  }
}

const onTableChange = (pagination: any) => {
  page.value = pagination.current || 1
  size.value = pagination.pageSize || 15
  fetchMemories()
}

const onSearch = async () => {
  if (semanticSearch.value && searchQuery.value.trim()) {
    await performSemanticSearch()
  } else {
    page.value = 1
    searchResults.value = []
    await fetchMemories()
  }
}

const performSemanticSearch = async () => {
  if (!searchQuery.value.trim()) {
    searchResults.value = []
    return
  }
  try {
    const res = await memoryApi.searchMemories(agentId.value, searchQuery.value, {
      limit: 20,
      type: activeTab.value !== 'all' ? activeTab.value : undefined,
    })
    // 注意：POST /memory/search 当前 405 断链（真端点为 /enhanced-memory-search/search，
    // 返回 {results: []} 结构），此处维持既有解析，待断链修复时一并调整
    searchResults.value = Array.isArray(res.data) ? res.data : []
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
    searchResults.value = []
  }
}

const fetchStats = async () => {
  loadingStats.value = true
  try {
    const res = await memoryApi.getMemoryStats(agentId.value)
    memoryStats.value = res.data ?? null
  } catch (e: any) {
    console.error('Failed to fetch memory stats:', e?.response?.data?.message || e?.message)
  } finally {
    loadingStats.value = false
  }
}

const fetchMemories = async () => {
  loading.value = true
  try {
    // 后端 GET /memory 实参: query/category/limit（暂无 offset 分页）
    const params: Record<string, any> = {
      limit: size.value,
    }
    if (categoryFilter.value) params.category = categoryFilter.value
    if (searchQuery.value && !semanticSearch.value) params.query = searchQuery.value

    const res = await memoryApi.getMemories(agentId.value, params)
    const { items, total: t } = memoryApi.extractMemoryList(res?.data)
    memories.value = items
    total.value = t
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const createMemory = async () => {
  creating.value = true
  try {
    await memoryApi.createMemory(
      {
        content: createForm.value.content,
        type: createForm.value.type,
        importance: createForm.value.importance,
        tags: createForm.value.tags.length > 0 ? createForm.value.tags : undefined,
      },
      agentId.value,
    )
    message.success(t('common.success'))
    showCreateModal.value = false
    createForm.value = { content: '', type: 'short_term', category: 'general', importance: 0.5, tags: [] }
    await fetchMemories()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    creating.value = false
  }
}

const viewMemory = async (record: MemoryEntry) => {
  try {
    const res = await memoryApi.getMemory(record.id)
    selectedMemory.value = { ...res.data }
  } catch {
    selectedMemory.value = { ...record }
  }
  editing.value = false
  showDetailModal.value = true
}

const updateMemory = async () => {
  if (!selectedMemory.value) return
  updating.value = true
  try {
    await memoryApi.updateMemory(selectedMemory.value.id, {
      content: selectedMemory.value.content,
    })
    message.success(t('common.success'))
    editing.value = false
    await fetchMemories()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    updating.value = false
  }
}

const deleteMemory = async (id: string) => {
  try {
    await memoryApi.deleteMemory(id)
    message.success(t('common.success'))
    await fetchMemories()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  }
}

// Renamed from deleteMemory for the popconfirm handler
const confirmDeleteMemory = deleteMemory

// --- New memory enhancement handlers ---

const fetchHotMemories = async () => {
  loading.value = true
  try {
    const res = await memoryApi.getHotMemories(agentId.value, size.value)
    const { items, total: t } = memoryApi.extractMemoryList(res?.data)
    memories.value = items
    total.value = t
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchCrystallizedMemories = async () => {
  loading.value = true
  try {
    const res = await memoryApi.getCrystallizedMemories(agentId.value, size.value)
    const { items, total: t } = memoryApi.extractMemoryList(res?.data)
    memories.value = items
    total.value = t
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const handleTriggerDecay = async () => {
  decaying.value = true
  try {
    const res = await memoryApi.triggerDecay(agentId.value)
    const decayed = (res as any)?.data?.decayed ?? 0
    message.success(`${t('memory.decay')}: ${decayed} memories decayed`)
    await fetchMemories()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    decaying.value = false
  }
}

const handleStrengthen = async (id: string) => {
  try {
    await memoryApi.strengthenMemory(id, 0.2, 'Manual strengthen from UI')
    message.success(t('memory.strengthen') + ' ✓')
    await fetchMemories()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  }
}

const handleForget = async (id: string) => {
  try {
    await memoryApi.forgetMemory(id, 'Manual forget from UI')
    message.success(t('memory.forget') + ' ✓')
    await fetchMemories()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  }
}

const handleExport = async () => {
  try {
    const res = await memoryApi.exportMemories({ format: 'json' })
    const data = (res as any)?.data ?? res
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `memories-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('memorySettings.exportSuccess'))
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  }
}

const handleImport = async () => {
  if (!importJson.value.trim()) {
    message.warning(t('validation.required'))
    return
  }
  importing.value = true
  try {
    const memories = JSON.parse(importJson.value)
    if (!Array.isArray(memories)) {
      message.error('JSON must be an array of memory objects')
      return
    }
    const res = await memoryApi.importMemories(memories, importMergeMode.value)
    const imported = (res as any)?.data?.imported ?? 0
    message.success(`${t('memory.importMem')}: ${imported} imported`)
    showImportModal.value = false
    importJson.value = ''
    await fetchMemories()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    importing.value = false
  }
}

const onImportFile = (file: File) => {
  const reader = new FileReader()
  reader.onload = () => {
    importJson.value = reader.result as string
  }
  reader.readAsText(file)
  return false
}

onMounted(() => {
  fetchMemories()
  fetchStats()
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

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
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

/* Type breakdown */
.type-breakdown {
  margin-top: -4px;
}

.breakdown-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin-bottom: 16px;
}

.breakdown-grid {
  display: flex;
  justify-content: space-around;
  gap: 20px;
}

.breakdown-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.breakdown-label {
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-transform: capitalize;
}

.breakdown-count {
  font-size: 14px;
  font-weight: 600;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-primary);
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  align-items: center;
}

.semantic-toggle {
  font-size: 13px;
  color: var(--nr-text-secondary);
}

/* Markdown view/edit modal (P1) */
.md-edit-btn {
  margin-left: auto;
}

.md-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.md-hint {
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.md-editor {
  font-family: var(--nr-font-mono, monospace);
  font-size: 12px;
}

.md-stats {
  margin-top: 8px;
  font-size: 12px;
  color: var(--nr-text-secondary);
}

/* Semantic search results */
.search-results {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-result-item {
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-score {
  font-size: 11px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
}

.result-content {
  font-size: 13px;
  color: var(--nr-text-primary);
  line-height: 1.5;
}

.result-date {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
  margin-top: 6px;
}

/* NeRF channel scores visualization */
.channel-scores-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 8px;
  background: rgba(255, 255, 255, 0.05);
}
.channel-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 4px;
  transition: width 0.3s ease;
}
.channel-label {
  font-size: 9px;
  color: white;
  font-weight: 500;
  white-space: nowrap;
  padding: 0 4px;
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

.metadata-json {
  font-family: var(--nr-font-mono);
  font-size: 11px;
  color: var(--nr-text-secondary);
  background: rgba(255, 255, 255, 0.03);
  padding: 8px 12px;
  border-radius: 6px;
  overflow-x: auto;
  max-height: 160px;
  margin: 0;
}
</style>
