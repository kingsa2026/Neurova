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
            :disabled="trashMode"
            allow-clear
            style="width: 240px"
          />
          <a-radio-group v-model:value="typeFilter" button-style="solid" size="small" :disabled="trashMode">
            <a-radio-button value="">{{ t('media.all') }}</a-radio-button>
            <a-radio-button value="image">{{ t('media.images') }}</a-radio-button>
            <a-radio-button value="audio">{{ t('media.audio') }}</a-radio-button>
            <a-radio-button value="video">{{ t('media.video') }}</a-radio-button>
          </a-radio-group>
        </div>
        <div class="toolbar-actions">
          <!-- 回收站读面不支持 search/media_type，所以进回收站时把那两个输入禁用而不是留着让人以为生效 -->
          <GlassButton :variant="trashMode ? 'primary' : 'ghost'" size="sm" @click="toggleTrashMode">
            {{ trashMode ? t('media.exitTrash') : t('media.trash') }}
          </GlassButton>
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
        <div v-if="mediaItems.length" class="media-grid">
          <GlassCard
            v-for="item in pagedMedia"
            :key="item.id"
            variant="default"
            class="media-card"
          >
            <div class="media-thumb" @click="openDetail(item)">
              <img v-if="item.type === 'image' && item.url" :src="item.url" :alt="item.name" />
              <div v-else class="thumb-placeholder">
                <span>{{ item.type === 'audio' ? '🎵' : item.type === 'file' ? '📄' : '🎬' }}</span>
                <span class="thumb-label">{{ item.name }}</span>
              </div>
            </div>
            <div class="media-card-footer">
              <span class="media-name">{{ item.name }}</span>
              <div class="media-card-actions">
                <template v-if="!trashMode">
                  <GlassButton variant="ghost" size="sm" @click="downloadMedia(item)">
                    {{ t('media.download') }}
                  </GlassButton>
                  <GlassButton variant="ghost" size="sm" @click="confirmTrash(item)">
                    {{ t('media.moveToTrash') }}
                  </GlassButton>
                  <GlassButton variant="danger" size="sm" @click="confirmDelete(item)">
                    {{ t('common.delete') }}
                  </GlassButton>
                </template>
                <template v-else>
                  <GlassButton variant="ghost" size="sm" @click="restoreItem(item)">
                    {{ t('media.restore') }}
                  </GlassButton>
                  <GlassButton variant="danger" size="sm" @click="confirmDeleteForever(item)">
                    {{ t('media.deleteForever') }}
                  </GlassButton>
                </template>
              </div>
            </div>
          </GlassCard>
        </div>
        <a-pagination v-if="mediaItems.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="mediaItems.length" size="small" style="margin-top: 16px; text-align: center" />
        <!-- 空态必须判"有没有条目"，不能挂在分页的 v-else 上：分页只在超过一页时才出现，
             于是 1..pageSize 条时两者都不成立，`v-else` 会把「暂无媒体文件」印在满屏卡片下面
             （2026-10-13 浏览器实跑抓到；vitest 测不到是因为 a-empty 的替身只渲染 slot、
             把写着文案的 description 属性丢掉了）。 -->
        <a-empty v-if="!mediaItems.length" :description="trashMode ? t('media.trashEmpty') : t('media.noMedia')" />
      </template>

      <!-- List View -->
      <template v-if="viewMode === 'list'">
        <GlassPanel>
          <a-table
            :columns="columns"
            :data-source="mediaItems"
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
                {{ formatDate(trashMode ? record.deleted_at : record.created_at) }}
              </template>
              <template v-if="column.key === 'actions'">
                <a-space>
                  <template v-if="!trashMode">
                    <GlassButton variant="ghost" size="sm" @click="openDetail(record)">
                      {{ t('media.detail') }}
                    </GlassButton>
                    <GlassButton variant="ghost" size="sm" @click="downloadMedia(record)">
                      {{ t('media.download') }}
                    </GlassButton>
                    <GlassButton variant="ghost" size="sm" @click="confirmTrash(record)">
                      {{ t('media.moveToTrash') }}
                    </GlassButton>
                    <GlassButton variant="danger" size="sm" @click="confirmDelete(record)">
                      {{ t('common.delete') }}
                    </GlassButton>
                  </template>
                  <template v-else>
                    <GlassButton variant="ghost" size="sm" @click="restoreItem(record)">
                      {{ t('media.restore') }}
                    </GlassButton>
                    <GlassButton variant="danger" size="sm" @click="confirmDeleteForever(record)">
                      {{ t('media.deleteForever') }}
                    </GlassButton>
                  </template>
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
            <a-spin v-if="!detailItem.url" size="small" />
            <img v-else-if="detailItem.type === 'image'" :src="detailItem.url" :alt="detailItem.name" style="max-width: 100%; border-radius: 8px" />
            <audio v-else-if="detailItem.type === 'audio'" controls :src="detailItem.url" style="width: 100%" />
            <video v-else-if="detailItem.type === 'video'" controls :src="detailItem.url" style="max-width: 100%; border-radius: 8px" />
            <span v-else>{{ detailItem.name }}</span>
          </div>
          <a-descriptions :column="2" bordered size="small" style="margin-top: 16px">
            <a-descriptions-item :label="t('media.metaName')">{{ detailItem.name }}</a-descriptions-item>
            <a-descriptions-item :label="t('media.metaType')">{{ detailItem.type }}</a-descriptions-item>
            <a-descriptions-item :label="t('media.metaSize')">{{ formatSize(detailItem.size) }}</a-descriptions-item>
            <a-descriptions-item :label="t('media.metaCreated')">{{ formatDate(detailItem.created_at) }}</a-descriptions-item>
          </a-descriptions>
        </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import * as mediaApi from '@/api/modules/media'

/** 页面视图模型：由后端 MediaItem（media_id/filename/media_type/size/created_at）映射而来。 */
interface MediaItem {
  id: string
  name: string
  type: 'image' | 'audio' | 'video' | 'file'
  /** 预览/播放用 object URL（后端无 url 字段，按需经 GET /media/{id} 拉取 blob 生成） */
  url?: string
  size?: number
  /** epoch 秒（后端 time.time()） */
  created_at?: number
  /** 回收站行的删除时刻（epoch 秒）；仅 /trash 读面带出 */
  deleted_at?: number
}

const props = defineProps<{ agentId: string }>()
const { t } = useI18n()

const mediaItems = ref<MediaItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const typeFilter = ref('')
const viewMode = ref<'grid' | 'list'>('grid')
/** 回收站开关（§6-158）：true 时读面切到 GET /media/trash，动作列换成「恢复 / 彻底删除」。 */
const trashMode = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const currentPage = ref(1)
const pageSize = ref(12)

// Detail modal
const detailVisible = ref(false)
const detailItem = ref<MediaItem | null>(null)

// 预览 object URL 缓存（组件卸载时统一 revoke）
const previewUrls = new Map<string, string>()

const viewOptions = [
  { label: '▦ Grid', value: 'grid' },
  { label: '☰ List', value: 'list' },
]

/**
 * 搜索后端化（台账 2026-09-11 ③）：数据源即服务端过滤结果，不做本地二次过滤——
 * 后端 search 同时匹配 filename 与 media_id，本地 name includes 会误删仅 id 命中的条目。
 * 类型过滤同理走服务端 media_type。
 */
const pagedMedia = computed(() =>
  mediaItems.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

const columns = computed(() => [
  { title: t('media.colName'), key: 'name', dataIndex: 'name' },
  { title: t('media.colType'), key: 'type', dataIndex: 'type', width: 100 },
  { title: t('media.colSize'), key: 'size', dataIndex: 'size', width: 100 },
  // 回收站里那列看的是"什么时候被删"，标题必须跟着换——沿用「创建时间」会把另一个读数贴上旧标签
  {
    title: trashMode.value ? t('media.colDeleted') : t('media.colCreated'),
    key: 'created_at',
    dataIndex: 'created_at',
    width: 160,
  },
  { title: t('media.colActions'), key: 'actions', width: 240 },
])

function formatSize(bytes?: number) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(d?: number) {
  return d ? new Date(d * 1000).toLocaleDateString() : '—'
}

/** 拉取媒体字节生成预览 object URL（带缓存；失败返回空串）。 */
async function resolvePreviewUrl(id: string): Promise<string> {
  const cached = previewUrls.get(id)
  if (cached) return cached
  try {
    const blob = await mediaApi.getMedia(id)
    const url = URL.createObjectURL(blob)
    previewUrls.set(id, url)
    return url
  } catch {
    return ''
  }
}

/** 为列表项按需加载预览 URL（图片缩略图 / 音视频详情播放）。 */
function loadPreviews() {
  // 回收站条目经现役内容面必 404（这正是"删掉了"的证据），不要去拉预览
  if (trashMode.value) return
  for (const item of mediaItems.value) {
    if (item.url) continue
    void resolvePreviewUrl(item.id).then((url) => {
      if (url) item.url = url
    })
  }
}

async function fetchMedia() {
  loading.value = true
  try {
    // 库与回收站共用这一处装配：只换读接口（GET /media/list ↔ GET /media/trash），
    // 映射、分页、失败提示都保持一份，不另起第二条取数路径。
    const res = trashMode.value
      ? await mediaApi.listTrash({ agent_id: props.agentId })
      : await mediaApi.listMedia({
          agent_id: props.agentId,
          media_type: typeFilter.value || undefined,
          search: searchQuery.value.trim() || undefined,
        })
    const items = res?.data?.media ?? []
    mediaItems.value = items.map((m) => ({
      id: m.media_id,
      name: m.filename,
      type: m.media_type as MediaItem['type'],
      url: '',
      size: m.size,
      created_at: m.created_at,
      deleted_at: m.deleted_at,
    }))
    loadPreviews()
  } catch {
    message.error(t('media.loadError'))
  } finally {
    loading.value = false
  }
}

/**
 * 回收站开关。切换即回到第一页并清空预览缓存——两侧的 object URL 不能互串：
 * 回收站条目经 `GET /media/{id}` 必 404，留着旧缓存会显示成"图还在"。
 */
function toggleTrashMode() {
  trashMode.value = !trashMode.value
  currentPage.value = 1
  previewUrls.forEach((url) => URL.revokeObjectURL(url))
  previewUrls.clear()
  mediaItems.value = mediaItems.value.map((item) => ({ ...item, url: '' }))
  void fetchMedia()
}

/**
 * 搜索/类型过滤走服务端（台账 2026-09-11 ③）：search 经 300ms 防抖后重拉，
 * 变化即回到第一页（offset=0 与既有分页协同）；类型切换立即重拉。
 * 连续输入经防抖合并为一次请求，避免每次按键都打后端。
 */
const SEARCH_DEBOUNCE_MS = 300
let searchTimer: ReturnType<typeof setTimeout> | undefined

watch(searchQuery, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = undefined
    currentPage.value = 1
    void fetchMedia()
  }, SEARCH_DEBOUNCE_MS)
})

watch(typeFilter, () => {
  currentPage.value = 1
  void fetchMedia()
})

function triggerUpload() {
  fileInputRef.value?.click()
}

async function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  for (const file of Array.from(input.files)) {
    try {
      await mediaApi.saveMedia(file, props.agentId)
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
  if (!item.url) {
    void resolvePreviewUrl(item.id).then((url) => {
      if (url && detailItem.value?.id === item.id) detailItem.value.url = url
    })
  }
}

async function downloadMedia(item: MediaItem) {
  // F-1：下载走后端 GET /media/download/{id} 字节流（原实现依赖不存在的 item.url）
  try {
    const blob = await mediaApi.downloadMedia(item.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = item.name
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    message.error(t('media.downloadError'))
  }
}

function confirmDelete(item: MediaItem) {
  Modal.confirm({
    title: t('media.confirmDelete'),
    content: item.name,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await mediaApi.deleteMedia(item.id)
        mediaItems.value = mediaItems.value.filter((m) => m.id !== item.id)
        message.success(t('media.deleteSuccess'))
      } catch {
        message.error(t('media.deleteError'))
      }
    },
  })
}

/** 移入回收站：后端只打标记、字节留盘，条目从现役读面消失并可从 /trash 读回。 */
function confirmTrash(item: MediaItem) {
  Modal.confirm({
    title: t('media.confirmTrash'),
    content: item.name,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await mediaApi.moveToTrash(item.id)
        mediaItems.value = mediaItems.value.filter((m) => m.id !== item.id)
        message.success(t('media.movedToTrash'))
      } catch {
        message.error(t('media.trashError'))
      }
    },
  })
}

async function restoreItem(item: MediaItem) {
  try {
    await mediaApi.restoreMedia(item.id)
    // 恢复后原字节要能被读到，缓存里那条"取不到"必须作废
    const cached = previewUrls.get(item.id)
    if (cached) {
      URL.revokeObjectURL(cached)
      previewUrls.delete(item.id)
    }
    message.success(t('media.restored'))
    await fetchMedia()
  } catch {
    message.error(t('media.restoreError'))
  }
}

/** 彻底删除：唯一会真删字节的回收站动作，标题与提示都按"不可恢复"说话。 */
function confirmDeleteForever(item: MediaItem) {
  Modal.confirm({
    title: t('media.confirmDeleteForever'),
    content: item.name,
    okText: t('common.confirm'),
    cancelText: t('common.cancel'),
    onOk: async () => {
      try {
        await mediaApi.deleteMedia(item.id, 'permanent')
        mediaItems.value = mediaItems.value.filter((m) => m.id !== item.id)
        message.success(t('media.deleteSuccess'))
      } catch {
        message.error(t('media.deleteError'))
      }
    },
  })
}

onMounted(fetchMedia)

onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
  previewUrls.forEach((url) => URL.revokeObjectURL(url))
  previewUrls.clear()
})
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
}

.media-thumb:hover img {
  opacity: 0.85;
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
