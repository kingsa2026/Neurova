<template>
  <div class="file-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.files') }}</h2>
      <div class="header-actions">
        <a-upload :before-upload="handleUpload" :show-upload-list="false">
          <GlassButton variant="primary" size="sm">{{ t('common.upload') }}</GlassButton>
        </a-upload>
      </div>
    </div>

    <!-- Storage info -->
    <GlassCard>
      <div class="storage-info">
        <div class="storage-item">
          <span class="storage-label">{{ t('file.totalStorage') }}</span>
          <span class="storage-value">{{ formatBytes(storageInfo.total ?? 0) }}</span>
        </div>
        <div class="storage-item">
          <span class="storage-label">{{ t('file.usedStorage') }}</span>
          <span class="storage-value">{{ formatBytes(storageInfo.used ?? 0) }}</span>
        </div>
        <div class="storage-item" style="flex: 1">
          <a-progress :percent="storagePercent" :stroke-color="storagePercent > 80 ? '#ef4444' : '#6366f1'" size="small" />
        </div>
      </div>
    </GlassCard>

    <!-- File list -->
    <GlassCard style="margin-top: 16px">
      <a-table
        :columns="columns"
        :data-source="files"
        :loading="loading"
        row-key="id"
        :pagination="{ current: page, pageSize: pageSize, total, showSizeChanger: true, onChange: onPageChange }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <div class="file-cell">
              <span class="file-icon">{{ getFileIcon(record.type || record.name) }}</span>
              <span class="file-name">{{ record.name }}</span>
            </div>
          </template>
          <template v-if="column.key === 'size'">
            <span class="mono">{{ formatBytes(record.size ?? 0) }}</span>
          </template>
          <template v-if="column.key === 'version'">
            <span class="mono">v{{ record.version ?? 1 }}</span>
          </template>
          <template v-if="column.key === 'actions'">
            <div class="file-actions">
              <GlassButton variant="ghost" size="sm" @click="previewFile(record)">{{ t('common.open') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="downloadFile(record)">{{ t('common.download') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="showHistory(record)">History</GlassButton>
              <GlassButton variant="danger" size="sm" @click="deleteFile(record.id)">{{ t('common.delete') }}</GlassButton>
            </div>
          </template>
        </template>
      </a-table>
    </GlassCard>

    <!-- Preview modal -->
    <a-modal v-model:open="showPreview" :title="previewFile?.name" :footer="null" width="640px">
      <div v-if="previewFile?.type?.startsWith('image/')" class="preview-image">
        <img :src="previewFile.url" :alt="previewFile.name" />
      </div>
      <pre v-else class="preview-text">{{ previewContent }}</pre>
    </a-modal>

    <!-- Version history modal -->
    <a-modal v-model:open="showHistoryModal" :title="t('file.versionHistory')" :footer="null">
      <a-timeline>
        <a-timeline-item v-for="ver in versions" :key="ver.version" :color="ver.version === currentVersion ? 'green' : 'gray'">
          <div class="version-item">
            <span>v{{ ver.version }} - {{ formatTime(ver.created_at) }}</span>
            <span class="version-size">{{ formatBytes(ver.size ?? 0) }}</span>
          </div>
        </a-timeline-item>
      </a-timeline>
      <a-empty v-if="!versions.length" :description="t('common.noData')" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const files = ref<any[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const storageInfo = ref<Record<string, any>>({ total: 0, used: 0 })
const showPreview = ref(false)
const showHistoryModal = ref(false)
const previewFile = ref<any>(null)
const previewContent = ref('')
const versions = ref<any[]>([])
const currentVersion = ref(1)

const storagePercent = computed(() => {
  const total = storageInfo.value.total || 1
  return Math.round(((storageInfo.value.used || 0) / total) * 100)
})

const columns = computed(() => [
  { title: t('common.name'), key: 'name' },
  { title: t('file.size'), key: 'size', width: 100 },
  { title: t('common.type'), dataIndex: 'type', key: 'type', width: 100 },
  { title: t('file.version'), key: 'version', width: 80 },
  { title: t('common.createdAt'), dataIndex: 'created_at', key: 'created_at', width: 160 },
  { title: t('common.actions'), key: 'actions', width: 260 },
])

const formatBytes = (bytes: number) => {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const getFileIcon = (name: string) => {
  if (/\.(png|jpg|jpeg|gif|svg|webp)$/i.test(name)) return '🖼️'
  if (/\.(pdf)$/i.test(name)) return '📄'
  if (/\.(doc|docx)$/i.test(name)) return '📝'
  if (/\.(zip|tar|gz)$/i.test(name)) return '📦'
  return '📁'
}

const fetchFiles = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/files', { params: { page: page.value, page_size: pageSize.value } })
    const data = res?.data ?? res ?? {}
    files.value = data.items ?? data.files ?? (Array.isArray(data) ? data : [])
    total.value = data.total ?? files.value.length
    storageInfo.value = data.storage ?? storageInfo.value
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const handleUpload = async (file: File) => {
  try {
    const formData = new FormData()
    formData.append('file', file)
    await request.post('/files/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    message.success(t('common.success'))
    await fetchFiles()
  } catch {
    message.error(t('common.error'))
  }
  return false
}

const previewFileFn = async (record: any) => {
  previewFile.value = record
  if (record.type?.startsWith('image/')) {
    previewContent.value = ''
  } else {
    try {
      const res: any = await request.get(`/files/${record.id}/content`)
      previewContent.value = typeof res === 'string' ? res : JSON.stringify(res, null, 2)
    } catch {
      previewContent.value = t('common.error')
    }
  }
  showPreview.value = true
}

const downloadFile = (record: any) => {
  const a = document.createElement('a')
  a.href = record.url || `/api/v1/files/${record.id}/download`
  a.download = record.name
  a.click()
}

const showHistory = async (record: any) => {
  currentVersion.value = record.version ?? 1
  try {
    const res: any = await request.get(`/files/${record.id}/versions`)
    versions.value = res?.data ?? res ?? []
  } catch {
    versions.value = []
  }
  showHistoryModal.value = true
}

const deleteFile = (id: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await request.delete(`/files/${id}`)
        message.success(t('common.success'))
        await fetchFiles()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

const onPageChange = (p: number, ps: number) => { page.value = p; pageSize.value = ps; fetchFiles() }

onMounted(fetchFiles)
</script>

<style scoped>
.file-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }
.storage-info { display: flex; align-items: center; gap: 20px; }
.storage-item { display: flex; flex-direction: column; gap: 4px; }
.storage-label { font-size: 12px; color: var(--nr-text-tertiary); }
.storage-value { font-weight: 600; color: var(--nr-text-primary); font-family: var(--nr-font-mono); }
.file-cell { display: flex; align-items: center; gap: 8px; }
.file-icon { font-size: 18px; }
.file-name { font-weight: 500; color: var(--nr-text-primary); }
.file-actions { display: flex; gap: 4px; }
.mono { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-secondary); }
.preview-image img { max-width: 100%; border-radius: 8px; }
.preview-text { background: rgba(0,0,0,0.3); padding: 16px; border-radius: 8px; font-size: 12px; color: var(--nr-text-secondary); font-family: var(--nr-font-mono); max-height: 400px; overflow: auto; white-space: pre-wrap; margin: 0; }
.version-item { display: flex; justify-content: space-between; }
.version-size { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }
</style>
