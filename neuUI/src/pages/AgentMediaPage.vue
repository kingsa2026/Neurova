<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><PictureOutlined :style="{color:'#06b6d4'}"/> 媒体处理</h2>
    </div>
    <a-radio-group v-model:value="tab" button-style="solid" size="small" class="glass-effect" style="padding:10px 16px;border-radius:10px">
      <a-radio-button value="image">图片</a-radio-button>
      <a-radio-button value="audio">音频</a-radio-button>
      <a-radio-button value="video">视频</a-radio-button>
    </a-radio-group>
    <div class="grid">
      <div v-for="m in list" :key="m.id" class="card glass-effect card-hover">
        <div class="thumb" :style="{background:getMediaColor(m.type)+'15'}">
          <component :is="getMediaIcon(m.type)" :style="{color:getMediaColor(m.type),fontSize:'2rem'}"/>
        </div>
        <div class="info">
          <span class="n">{{ m.name }}</span>
          <span class="sz">{{ formatFileSize(m.size) }}</span>
          <span class="tm">{{ formatTime(m.created_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { PictureOutlined, AudioOutlined, PlaySquareOutlined, FileImageOutlined } from '@ant-design/icons-vue'
import { filesAPI } from '@/api/modules/files_api'
import { useAgentPage } from '@/composables/useAgentPage'
import { message } from 'ant-design-vue'

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/media', () => loadFiles())

const tab = ref('image')
interface MediaFile {
  id: string
  name: string
  type: string
  size: number
  created_at: string
}
const files = ref<MediaFile[]>([])
const loading = ref(false)

const list = computed(() => {
  return files.value.filter(d => {
    if (tab.value === 'image') return d.type === 'image' || d.name.match(/\.(png|jpg|jpeg|gif|webp|svg)$/i)
    if (tab.value === 'audio') return d.type === 'audio' || d.name.match(/\.(mp3|wav|ogg|flac|aac)$/i)
    if (tab.value === 'video') return d.type === 'video' || d.name.match(/\.(mp4|webm|mov|avi|mkv)$/i)
    return true
  })
})

const getMediaIcon = (type: string) => {
  if (type === 'image' || type?.match(/image/)) return FileImageOutlined
  if (type === 'audio' || type?.match(/audio/)) return AudioOutlined
  if (type === 'video' || type?.match(/video/)) return PlaySquareOutlined
  return PictureOutlined
}

const getMediaColor = (type: string) => {
  if (type === 'image' || type?.match(/image/)) return '#3b82f6'
  if (type === 'audio' || type?.match(/audio/)) return '#8b5cf6'
  if (type === 'video' || type?.match(/video/)) return '#f59e0b'
  return '#06b6d4'
}

const formatFileSize = (bytes: number) => {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}

const formatTime = (time: string) => {
  if (!time) return ''
  const d = new Date(time)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const loadFiles = async () => {
  loading.value = true
  try {
    const res = await filesAPI.list(agentId.value)
    if (res.data) {
      files.value = res.data
    }
  } catch (err) {
    console.error('加载文件失败:', err)
    message.error('加载文件失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await initAgent()
  loadFiles()
})
</script>

<style scoped>
.pg {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.hd {
  padding: 16px 24px;
  border-radius: 12px;
}
.t {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 14px;
}
.card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 24px 16px;
  border-radius: 12px;
  cursor: pointer;
}
.thumb {
  width: 72px;
  height: 72px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.info {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.n {
  color: #e2e8f0;
  font-size: 0.85rem;
}
.sz {
  color: rgba(255, 255, 255, 0.35);
  font-size: 0.78rem;
}
.tm {
  color: rgba(255, 255, 255, 0.2);
  font-size: 0.72rem;
}
</style>
