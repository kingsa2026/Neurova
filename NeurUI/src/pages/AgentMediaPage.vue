<template>
  <div class="media-page">
    <!-- Toolbar -->
    <GlassPanel class="media-toolbar">
      <div class="toolbar-row">
        <div class="toolbar-left">
          <h2 class="page-title">{{ t('media.title') }}</h2>
          <a-input-search
            v-model:value="searchQuery"
            :placeholder="t('media.searchPlaceholder')"
            allow-clear
            style="width: 240px"
          />
          <a-radio-group v-model:value="typeFilter" button-style="solid" size="small">
            <a-radio-button value="">{{ t('media.all') }}</a-radio-button>
            <a-radio-button value="image">{{ t('media.images') }}</a-radio-button>
            <a-radio-button value="audio">{{ t('media.audio') }}</a-radio-button>
            <a-radio-button value="video">{{ t('media.video') }}</a-radio-button>
          </a-radio-group>
        </div>
        <div class="toolbar-actions">
          <a-segmented v-model:value="viewMode" :options="viewOptions" />
          <GlassButton variant="primary" size="sm" @click="triggerUpload">
            {{ t('media.upload') }}
          </GlassButton>
          <input ref="fileInputRef" type="file" accept="image/*,audio/*,video/*" multiple hidden @change="onFileSelected" />
        </div>
      </div>
    </GlassPanel>

    <!-- Content -->
    <a-spin :spinning="loading">
      <!-- Grid View -->
      <template v-if="viewMode === 'grid'">
        <div v-if="filteredMedia.length" class="media-grid">
          <GlassCard
            v-for="item in filteredMedia"
            :key="item.id"
            variant="default"
            class="media-card"
          >
            <div class="media-thumb" @click="openDetail(item)">
              <img v-if="item.type === 'image'" :src="item.thumbnail_url ?? item.url" :alt="item.name" />
              <div v-else class="thumb-placeholder">
                <span>{{ item.type === 'audio' ? '🎵' : '🎬' }}</span>
                <span class="thumb-label">{{ item.name }}</span>
              </div>
            </div>
            <div class="media-card-footer">
              <span class="media-name">{{ item.name }}</span>
              <div class="media-card-actions">
                <GlassButton variant="ghost" size="sm" @click="downloadMedia(item)">
                  {{ t('media.download') }}
                </GlassButton>
                <GlassButton variant="danger" size="sm" @click="confirmDelete(item)">
                  {{ t('common.delete') }}
                </GlassButton>
              </div>
            </div>
          </GlassCard>
        </div>
        <a-empty v-else :description="t('media.noMedia')" />
      </template>

      <!-- List View -->
      <template v-if="viewMode === 'list'">
        <GlassPanel>
          <a-table
            :columns="columns"
            :data-source="filteredMedia"
            :loading="loading"
            :pagination="{ pageSize: 20 }"
            row-key="id"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <div class="list-name-cell">
                  <span>{{ record.type === 'image' ? '🖼️' : record.type === 'audio' ? '🎵' : '🎬' }}</span>
                  <span class="media-name">{{ record.name }}</span>
                </div>
              </template>
              <template v-if="column.key === 'type'">
                <a-tag :color="record.type === 'image' ? 'blue' : record.type === 'audio' ? 'green' : 'orange'">
                  {{ record.type }}
                </a-tag>
              </template>
              <template v-if="column.key === 'size'">
                {{ formatSize(record.size) }}
              </template>
              <template v-if="column.key === 'created_at'">
                {{ formatDate(record.created_at) }}
              </template>
              <template v-if="column.key === 'actions'">
                <a-space>
                  <GlassButton variant="ghost" size="sm" @click="openDetail(record)">
                    {{ t('media.detail') }}
                  </GlassButton>
                  <GlassButton variant="ghost" size="sm" @click="downloadMedia(record)">
                    {{ t('media.download') }}
                  </GlassButton>
                  <GlassButton variant="danger" size="sm" @click="confirmDelete(record)">
                    {{ t('common.delete') }}
                  </GlassButton>
                </a-space>
              </template>
            </template>
          </a-table>
        </GlassPanel>
      </template>
    </a-spin>

    <!-- Detail Modal -->
    <a-modal
      v-model:open="detailVisible"
      :title="detailItem?.name ?? t('media.detail')"
      :footer="null"
      width="680px"
    >
      <div v-if="detailItem" class="detail-body">
        <div class="detail-preview">
          <img v-if="detailItem.type === 'image'" :src="detailItem.url" :alt="detailItem.name" style="max-width: 100%; border-radius: 8px" />
          <audio v-else-if="detailItem.type === 'audio'" controls :src="detailItem.url" style="width: 100%" />
          <video v-else-if="detailItem.type === 'video'" controls :src="detailItem.url" style="max-width: 100%; border-radius: 8px" />
        </div>
        <a-descriptions :column="2" bordered size="small" style="margin-top: 16px">
          <a-descriptions-item :label="t('media.metaName')">{{ detailItem.name }}</a-descriptions-item>
          <a-descriptions-item :label="t('media.metaType')">{{ detailItem.type }}</a-descriptions-item>
          <a-descriptions-item :label="t('media.metaSize')">{{ formatSize(detailItem.size) }}</a-descriptions-item>
          <a-descriptions-item v-if="detailItem.width" :label="t('media.dimensions')">
            {{ detailItem.width }} x {{ detailItem.height }}
          </a-descriptions-item>
          <a-descriptions-item v-if="detailItem.duration" :label="t('media.duration')">
            {{ detailItem.duration }}s
          </a-descriptions-item>
          <a-descriptions-item :label="t('media.metaCreated')">{{ formatDate(detailItem.created_at) }}</a-descriptions-item>
        </a-descriptions>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

interface MediaItem {
  id: string
  name: string
  type: 'image' | 'audio' | 'video'
  url: string
  thumbnail_url?: string
  size?: number
  width?: number
  height?: number
  duration?: number
  created_at?: string
}

const props = defineProps<{ agentId: string }>()
const { t } = useI18n()

const mediaItems = ref<MediaItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const typeFilter = ref('')
const viewMode = ref<'grid' | 'list'>('grid')
const fileInputRef = ref<HTMLInputElement | null>(null)

// Detail modal
const detailVisible = ref(false)
const detailItem = ref<MediaItem | null>(null)

const viewOptions = [
  { label: '▦ Grid', value: 'grid' },
  { label: '☰ List', value: 'list' },
]

const filteredMedia = computed(() => {
  let list = mediaItems.value
  if (typeFilter.value) {
    list = list.filter((m) => m.type === typeFilter.value)
  }
  const q = searchQuery.value.toLowerCase()
  if (q) {
    list = list.filter((m) => m.name.toLowerCase().includes(q))
  }
  return list
})

const columns = computed(() => [
  { title: t('media.colName'), key: 'name', dataIndex: 'name' },
  { title: t('media.colType'), key: 'type', dataIndex: 'type', width: 100 },
  { title: t('media.colSize'), key: 'size', dataIndex: 'size', width: 100 },
  { title: t('media.colCreated'), key: 'created_at', dataIndex: 'created_at', width: 160 },
  { title: t('media.colActions'), key: 'actions', width: 240 },
])

function formatSize(bytes?: number) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(d?: string) {
  return d ? new Date(d).toLocaleDateString() : '—'
}

async function fetchMedia() {
  loading.value = true
  try {
    const res: any = await request.get(`/media/list?agent_id=${props.agentId}`)
    const data = res?.data ?? res
    mediaItems.value = Array.isArray(data) ? data : data?.items ?? data?.media ?? []
  } catch {
    message.error(t('media.loadError'))
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
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('agent_id', props.agentId)
      await request.post('/media/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    } catch {
      message.error(t('media.uploadError'))
    }
  }
  input.value = ''
  message.success(t('media.uploadSuccess'))
  fetchMedia()
}

function openDetail(item: MediaItem) {
  detailItem.value = item
  detailVisible.value = true
}

function downloadMedia(item: MediaItem) {
  const a = document.createElement('a')
  a.href = item.url
  a.download = item.name
  a.click()
}

function confirmDelete(item: MediaItem) {
  Modal.confirm({
    title: t('media.confirmDelete'),
    content: item.name,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await request.delete(`/media/${item.id}`)
        mediaItems.value = mediaItems.value.filter((m) => m.id !== item.id)
        message.success(t('media.deleteSuccess'))
      } catch {
        message.error(t('media.deleteError'))
      }
    },
  })
}

onMounted(fetchMedia)
</script>

<style scoped>
.media-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.media-toolbar .toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-actions {
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

.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.media-card {
  overflow: hidden;
}

.media-thumb {
  aspect-ratio: 1;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  background: rgba(0, 0, 0, 0.15);
}

.media-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s;
}

.media-thumb:hover img {
  transform: scale(1.05);
}

.thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 36px;
}

.thumb-label {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  max-width: 90%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.media-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
}

.media-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.media-card-actions {
  display: flex;
  gap: 4px;
}

.list-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.detail-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  padding: 12px;
  min-height: 200px;
}
</style>
