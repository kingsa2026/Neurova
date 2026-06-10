<template>
  <div class="file-page">
    <!-- Storage Info -->
    <div class="file-stats">
      <GlassStatCard :label="t('file.totalFiles')" :value="files.length" emoji="📄" />
      <GlassStatCard :label="t('file.storageUsed')" :value="storageDisplay" emoji="💾" />
    </div>

    <!-- Toolbar -->
    <GlassPanel class="file-toolbar">
      <div class="toolbar-row">
        <a-input-search
          v-model:value="searchQuery"
          :placeholder="t('file.searchPlaceholder')"
          allow-clear
          style="max-width: 300px"
        />
        <div class="toolbar-actions">
          <GlassButton variant="primary" size="sm" @click="triggerUpload">
            {{ t('file.upload') }}
          </GlassButton>
          <input ref="fileInputRef" type="file" multiple hidden @change="onFileSelected" />
        </div>
      </div>
    </GlassPanel>

    <!-- Upload Drop Zone -->
    <GlassPanel v-if="showDropZone" class="drop-zone" variant="subtle" @click="triggerUpload">
      <div class="drop-zone-inner">
        <span class="drop-icon">📁</span>
        <span class="drop-text">{{ t('file.dragDrop') }}</span>
      </div>
    </GlassPanel>

    <!-- File Table -->
    <GlassPanel>
      <a-table
        :columns="columns"
        :data-source="filteredFiles"
        :loading="loading"
        :pagination="{ pageSize: 15 }"
        row-key="id"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <div class="file-name-cell">
              <span class="file-icon">{{ getFileIcon(record.type) }}</span>
              <span v-if="record._renaming">
                <a-input
                  v-model:value="record._renameValue"
                  size="small"
                  @press-enter="confirmRename(record)"
                  style="width: 180px"
                />
              </span>
              <span v-else class="file-name">{{ record.name }}</span>
            </div>
          </template>
          <template v-if="column.key === 'type'">
            <a-tag>{{ record.type ?? 'unknown' }}</a-tag>
          </template>
          <template v-if="column.key === 'size'">
            {{ formatSize(record.size) }}
          </template>
          <template v-if="column.key === 'status'">
            <a-badge :status="record.status === 'ready' ? 'success' : 'processing'" :text="record.status" />
          </template>
          <template v-if="column.key === 'created_at'">
            {{ formatDate(record.created_at) }}
          </template>
          <template v-if="column.key === 'actions'">
            <a-space>
              <GlassButton variant="ghost" size="sm" @click="previewFile(record)">
                {{ t('file.preview') }}
              </GlassButton>
              <GlassButton variant="ghost" size="sm" @click="downloadFile(record)">
                {{ t('file.download') }}
              </GlassButton>
              <GlassButton variant="ghost" size="sm" @click="startRename(record)">
                {{ t('file.rename') }}
              </GlassButton>
              <GlassButton variant="danger" size="sm" @click="confirmDelete(record)">
                {{ t('common.delete') }}
              </GlassButton>
            </a-space>
          </template>
        </template>
      </a-table>
    </GlassPanel>

    <!-- Preview Modal -->
    <a-modal
      v-model:open="previewVisible"
      :title="previewFileItem?.name ?? t('file.preview')"
      :footer="null"
      width="720px"
    >
      <div v-if="previewFileItem" class="preview-body">
        <template v-if="isImage(previewFileItem)">
          <img :src="previewUrl" alt="Preview" style="max-width: 100%; border-radius: 8px" />
        </template>
        <template v-else-if="isText(previewFileItem)">
          <pre class="text-preview">{{ previewContent }}</pre>
        </template>
        <template v-else-if="isPdf(previewFileItem)">
          <iframe :src="previewUrl" width="100%" height="480px" style="border: none; border-radius: 8px" />
        </template>
        <template v-else>
          <a-empty :description="t('file.noPreview')" />
        </template>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'

interface FileItem {
  id: string
  name: string
  type?: string
  size?: number
  status?: string
  created_at?: string
  _renaming?: boolean
  _renameValue?: string
}

const props = defineProps<{ agentId: string }>()
const { t } = useI18n()

const files = ref<FileItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)
const showDropZone = ref(true)

// Preview
const previewVisible = ref(false)
const previewFileItem = ref<FileItem | null>(null)
const previewUrl = ref('')
const previewContent = ref('')

const filteredFiles = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return files.value
  return files.value.filter((f) => f.name.toLowerCase().includes(q))
})

const storageDisplay = computed(() => {
  const total = files.value.reduce((sum, f) => sum + (f.size ?? 0), 0)
  return formatSize(total)
})

const columns = computed(() => [
  { title: t('file.colName'), key: 'name', dataIndex: 'name' },
  { title: t('file.colType'), key: 'type', dataIndex: 'type', width: 100 },
  { title: t('file.colSize'), key: 'size', dataIndex: 'size', width: 100 },
  { title: t('file.colStatus'), key: 'status', dataIndex: 'status', width: 100 },
  { title: t('file.colCreated'), key: 'created_at', dataIndex: 'created_at', width: 160 },
  { title: t('file.colActions'), key: 'actions', width: 280 },
])

function formatSize(bytes?: number) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatDate(d?: string) {
  return d ? new Date(d).toLocaleDateString() : '—'
}

function getFileIcon(type?: string) {
  if (!type) return '📄'
  if (type.startsWith('image')) return '🖼️'
  if (type.startsWith('video')) return '🎬'
  if (type.startsWith('audio')) return '🎵'
  if (type.includes('pdf')) return '📕'
  if (type.includes('text') || type.includes('json') || type.includes('xml')) return '📝'
  if (type.includes('zip') || type.includes('rar') || type.includes('tar')) return '📦'
  return '📄'
}

function isImage(f: FileItem) { return f.type?.startsWith('image') }
function isText(f: FileItem) {
  return f.type?.includes('text') || f.type?.includes('json') || f.type?.includes('xml') || f.name?.endsWith('.txt') || f.name?.endsWith('.md')
}
function isPdf(f: FileItem) { return f.type?.includes('pdf') || f.name?.endsWith('.pdf') }

async function fetchFiles() {
  loading.value = true
  try {
    const res: any = await request.get(`/files?agent_id=${props.agentId}`)
    const data = res?.data ?? res
    files.value = (Array.isArray(data) ? data : data?.items ?? data?.files ?? []).map((f: any) => ({
      ...f,
      _renaming: false,
      _renameValue: '',
    }))
  } catch {
    message.error(t('file.loadError'))
  } finally {
    loading.value = false
  }
}

function triggerUpload() {
  fileInputRef.value?.click()
}

async function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  for (const file of Array.from(input.files)) {
    await uploadFile(file)
  }
  input.value = ''
}

async function uploadFile(file: File) {
  try {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('agent_id', props.agentId)
    await request.post('/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    message.success(t('file.uploadSuccess'))
    fetchFiles()
  } catch {
    message.error(t('file.uploadError'))
  }
}

async function previewFile(file: FileItem) {
  previewFileItem.value = file
  previewUrl.value = ''
  previewContent.value = ''

  if (isImage(file) || isPdf(file)) {
    previewUrl.value = `/api/v1/files/${file.id}/download`
  } else if (isText(file)) {
    try {
      const res: any = await request.get(`/files/${file.id}/download`, { responseType: 'text' })
      previewContent.value = typeof res === 'string' ? res : JSON.stringify(res, null, 2)
    } catch {
      previewContent.value = t('file.previewError')
    }
  }
  previewVisible.value = true
}

async function downloadFile(file: FileItem) {
  try {
    const a = document.createElement('a')
    a.href = `/api/v1/files/${file.id}/download`
    a.download = file.name
    a.click()
  } catch {
    message.error(t('file.downloadError'))
  }
}

function startRename(file: FileItem) {
  file._renaming = true
  file._renameValue = file.name
}

async function confirmRename(file: FileItem) {
  if (!file._renameValue?.trim() || file._renameValue === file.name) {
    file._renaming = false
    return
  }
  try {
    await request.put(`/files/${file.id}`, { name: file._renameValue })
    file.name = file._renameValue
    file._renaming = false
    message.success(t('file.renameSuccess'))
  } catch {
    message.error(t('file.renameError'))
  }
}

function confirmDelete(file: FileItem) {
  Modal.confirm({
    title: t('file.confirmDelete'),
    content: file.name,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await request.delete(`/files/${file.id}`)
        files.value = files.value.filter((f) => f.id !== file.id)
        message.success(t('file.deleteSuccess'))
      } catch {
        message.error(t('file.deleteError'))
      }
    },
  })
}

// Drag & drop handlers
function onDragOver(e: DragEvent) { e.preventDefault(); showDropZone.value = true }
function onDrop(e: DragEvent) {
  e.preventDefault()
  const droppedFiles = e.dataTransfer?.files
  if (droppedFiles?.length) {
    Array.from(droppedFiles).forEach(uploadFile)
  }
}

onMounted(() => {
  fetchFiles()
  document.addEventListener('dragover', onDragOver)
  document.addEventListener('drop', onDrop)
})

onUnmounted(() => {
  document.removeEventListener('dragover', onDragOver)
  document.removeEventListener('drop', onDrop)
})
</script>

<style scoped>
.file-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.file-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}

.file-toolbar .toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.drop-zone {
  cursor: pointer;
}

.drop-zone-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  gap: 8px;
  border: 2px dashed rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  transition: all 0.2s;
}

.drop-zone-inner:hover {
  border-color: var(--nr-primary);
  background: rgba(99, 102, 241, 0.04);
}

.drop-icon {
  font-size: 32px;
}

.drop-text {
  font-size: 13px;
  color: var(--nr-text-tertiary);
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-icon {
  font-size: 18px;
}

.file-name {
  font-weight: 500;
  color: var(--nr-text-primary);
}

.preview-body {
  max-height: 520px;
  overflow: auto;
}

.text-preview {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 16px;
  font-family: var(--nr-font-mono);
  font-size: 13px;
  color: var(--nr-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
