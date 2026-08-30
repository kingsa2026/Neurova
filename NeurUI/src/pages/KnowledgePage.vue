<template>
  <div class="knowledge-page">
    <!-- Header & Toolbar -->
    <GlassPanel class="kb-header">
      <div class="header-row">
        <div class="header-left">
          <h2 class="page-title">{{ t('knowledge.title') }}</h2>
          <a-input-search
            v-model:value="searchQuery"
            :placeholder="t('knowledge.searchPlaceholder')"
            allow-clear
            style="width: 260px"
            @search="handleSearch"
          />
          <a-checkbox v-model:checked="semanticSearch">{{ t('knowledge.semanticSearch') }}</a-checkbox>
        </div>
        <div class="header-actions">
          <a-select
            v-model:value="activeCategory"
            :options="categoryOptions"
            :placeholder="t('knowledge.filterCategory')"
            allow-clear
            style="min-width: 160px"
            @change="fetchKnowledge"
          />
          <GlassButton variant="secondary" size="sm" @click="exportKnowledge">
            {{ t('knowledge.export') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="importVisible = true">
            {{ t('knowledge.import') }}
          </GlassButton>
          <GlassButton variant="primary" size="sm" @click="openCreateModal">
            {{ t('knowledge.create') }}
          </GlassButton>
        </div>
      </div>
    </GlassPanel>

    <!-- Knowledge Table -->
    <GlassPanel v-if="knowledgeItems.length > 0 || loading">
      <a-table
        :columns="columns"
        :data-source="knowledgeItems"
        :loading="loading"
        :locale="{ emptyText: '' }"
        :pagination="pagination"
        row-key="id"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'title'">
            <span class="kb-title-cell">{{ record.title }}</span>
          </template>
          <template v-if="column.key === 'category'">
            <a-tag color="blue">{{ record.category }}</a-tag>
          </template>
          <template v-if="column.key === 'content'">
            <span class="kb-preview">{{ truncate(record.content, 80) }}</span>
          </template>
          <template v-if="column.key === 'created_at'">
            {{ formatDate(record.created_at) }}
          </template>
          <template v-if="column.key === 'actions'">
            <a-space>
              <GlassButton variant="ghost" size="sm" @click="editItem(record)">
                {{ t('common.edit') }}
              </GlassButton>
              <GlassButton variant="danger" size="sm" @click="confirmDelete(record)">
                {{ t('common.delete') }}
              </GlassButton>
            </a-space>
          </template>
        </template>
      </a-table>
    </GlassPanel>
    <GlassPanel v-else>
      <a-empty :description="t('common.noData')" />
    </GlassPanel>

    <!-- Create / Edit Modal -->
    <a-modal
      v-model:open="modalVisible"
      :title="editingItem ? t('knowledge.editItem') : t('knowledge.createItem')"
      :confirm-loading="saving"
      width="640px"
      @ok="saveItem"
      @cancel="modalVisible = false"
    >
      <a-form layout="vertical" :rules="{ title: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('knowledge.itemTitle')">
          <a-input v-model:value="form.title" :placeholder="t('knowledge.titlePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemCategory')">
          <a-input v-model:value="form.category" :placeholder="t('knowledge.categoryPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemContent')">
          <a-textarea v-model:value="form.content" :rows="10" :placeholder="t('knowledge.contentPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('knowledge.itemTags')">
          <a-select
            v-model:value="form.tags"
            mode="tags"
            :placeholder="t('knowledge.tagsPlaceholder')"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Import Modal -->
    <a-modal
      v-model:open="importVisible"
      :title="t('knowledge.importTitle')"
      @ok="handleImport"
      :confirm-loading="importing"
    >
      <a-upload-dragger
        :file-list="importFiles"
        :before-upload="beforeImportUpload"
        :multiple="false"
        accept=".json,.csv,.txt,.md,.html,.htm,.docx,.xlsx,.pptx,.pdf"
      >
        <p class="ant-upload-text">{{ t('knowledge.dragOrClick') }}</p>
        <p class="ant-upload-hint">{{ t('knowledge.importFormats') }}</p>
      </a-upload-dragger>

      <a-divider style="margin: 12px 0" />
      <a-input
        v-model:value="importUrlValue"
        :placeholder="t('knowledge.importUrlPlaceholder')"
        style="margin-bottom: 8px"
      />
      <a-button type="primary" block :loading="importingUrl" @click="handleImportUrl">
        {{ t('knowledge.importUrl') }}
      </a-button>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'
import {
  getKnowledgeNodes,
  searchKnowledge,
  createKnowledgeNode,
  updateKnowledgeNode,
  deleteKnowledgeNode,
} from '@/api/modules/knowledge'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'

interface KnowledgeItem {
  id: string
  title: string
  category: string
  content: string
  tags?: string[]
  created_at?: string
  updated_at?: string
}

const { t } = useI18n()

const { agentId } = useAgentPage({
  onAgentChange: () => {
    currentPage.value = 1
    fetchKnowledge()
  },
})

const knowledgeItems = ref<KnowledgeItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const semanticSearch = ref(false)
const activeCategory = ref<string | undefined>(undefined)
const totalItems = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

const categoryOptions = ref<{ label: string; value: string }[]>([])

// Modal
const modalVisible = ref(false)
const saving = ref(false)
const editingItem = ref<KnowledgeItem | null>(null)
const form = ref({ title: '', category: '', content: '', tags: [] as string[] })

// Import
const importVisible = ref(false)
const importing = ref(false)
const importFiles = ref<UploadFile[]>([])

const columns = computed(() => [
  { title: t('knowledge.colTitle'), key: 'title', dataIndex: 'title', ellipsis: true },
  { title: t('knowledge.colCategory'), key: 'category', dataIndex: 'category', width: 140 },
  { title: t('knowledge.colContent'), key: 'content', dataIndex: 'content', ellipsis: true },
  { title: t('knowledge.colCreated'), key: 'created_at', dataIndex: 'created_at', width: 160 },
  { title: t('knowledge.colActions'), key: 'actions', width: 180 },
])

const pagination = computed(() => ({
  current: currentPage.value,
  pageSize: pageSize.value,
  total: totalItems.value,
  showSizeChanger: true,
  showTotal: (total: number) => t('knowledge.totalItems', { total }),
}))

function truncate(str: string, len: number) {
  return str?.length > len ? str.slice(0, len) + '...' : str ?? ''
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString()
}

function onTableChange(pag: any) {
  currentPage.value = pag.current
  pageSize.value = pag.pageSize
  fetchKnowledge()
}

async function handleSearch() {
  if (semanticSearch.value && searchQuery.value.trim()) {
    await semanticSearchFn()
  } else {
    currentPage.value = 1
    await fetchKnowledge()
  }
}

async function fetchKnowledge() {
  loading.value = true
  try {
    const params: Record<string, any> = {
      agent_id: agentId.value,
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (searchQuery.value) params.q = searchQuery.value
    if (activeCategory.value) params.category = activeCategory.value

    const res: any = await getKnowledgeNodes(params)
    const data = res?.data ?? res
    knowledgeItems.value = Array.isArray(data) ? data : data?.items ?? []
    totalItems.value = data?.total ?? knowledgeItems.value.length

    // Extract categories from results
    const cats = new Set(knowledgeItems.value.map((i: KnowledgeItem) => i.category).filter(Boolean))
    if (cats.size && !categoryOptions.value.length) {
      categoryOptions.value = [...cats].map((c) => ({ label: c, value: c }))
    }
  } catch {
    message.error(t('knowledge.loadError'))
  } finally {
    loading.value = false
  }
}

async function semanticSearchFn() {
  loading.value = true
  try {
    const res: any = await searchKnowledge(searchQuery.value, {
      agent_id: agentId.value,
      page: currentPage.value,
      page_size: pageSize.value,
    })
    const data = res?.data ?? res
    knowledgeItems.value = Array.isArray(data) ? data : data?.items ?? data?.results ?? []
    totalItems.value = data?.total ?? knowledgeItems.value.length
  } catch {
    message.error(t('knowledge.searchError'))
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  editingItem.value = null
  form.value = { title: '', category: '', content: '', tags: [] }
  modalVisible.value = true
}

function editItem(item: KnowledgeItem) {
  editingItem.value = item
  form.value = {
    title: item.title,
    category: item.category,
    content: item.content,
    tags: item.tags ?? [],
  }
  modalVisible.value = true
}

async function saveItem() {
  saving.value = true
  try {
    if (editingItem.value) {
      await updateKnowledgeNode(editingItem.value.id, form.value, { agent_id: agentId.value })
      message.success(t('knowledge.updateSuccess'))
    } else {
      await createKnowledgeNode({ ...form.value, agent_id: agentId.value })
      message.success(t('knowledge.createSuccess'))
    }
    modalVisible.value = false
    fetchKnowledge()
  } catch {
    message.error(t('knowledge.saveError'))
  } finally {
    saving.value = false
  }
}

function confirmDelete(item: KnowledgeItem) {
  Modal.confirm({
    title: t('knowledge.confirmDelete'),
    content: item.title,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await deleteKnowledgeNode(item.id, { agent_id: agentId.value })
        knowledgeItems.value = knowledgeItems.value.filter((k) => k.id !== item.id)
        message.success(t('knowledge.deleteSuccess'))
      } catch {
        message.error(t('knowledge.deleteError'))
      }
    },
  })
}

function exportKnowledge() {
  const blob = new Blob([JSON.stringify(knowledgeItems.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'knowledge-export.json'
  a.click()
  URL.revokeObjectURL(url)
  message.success(t('knowledge.exportSuccess'))
}

function beforeImportUpload(file: File) {
  importFiles.value = [{ uid: '-1', name: file.name, status: 'done', originFileObj: file } as any]
  return false
}

async function handleImport() {
  if (!importFiles.value.length) return
  importing.value = true
  try {
    const file = (importFiles.value[0] as any).originFileObj as File
    const formData = new FormData()
    formData.append('file', file)
    await request.post('/knowledge/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: { agent_id: agentId.value },
    })
    message.success(t('knowledge.importSuccess'))
    importVisible.value = false
    importFiles.value = []
    fetchKnowledge()
  } catch {
    message.error(t('knowledge.importError'))
  } finally {
    importing.value = false
  }
}

onMounted(fetchKnowledge)
</script>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.kb-header .header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
  white-space: nowrap;
}

.kb-title-cell {
  font-weight: 500;
  color: var(--nr-text-primary);
}

.kb-preview {
  font-size: 13px;
  color: var(--nr-text-secondary);
}
</style>
