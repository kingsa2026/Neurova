&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;PictureOutlined :style="{color:'#06b6d4'}"/&gt; 媒体处理&lt;/h2&gt;
    &lt;/div&gt;
    &lt;a-radio-group v-model:value="tab" button-style="solid" size="small"  style="padding:10px 16px;border-radius:10px"&gt;
      &lt;a-radio-button value="image"&gt;图片&lt;/a-radio-button&gt;
      &lt;a-radio-button value="audio"&gt;音频&lt;/a-radio-button&gt;
      &lt;a-radio-button value="video"&gt;视频&lt;/a-radio-button&gt;
    &lt;/a-radio-group&gt;
    &lt;div &gt;
      &lt;div v-for="m in list" :key="m.id" &gt;
        &lt;div  :style="{background:getMediaColor(m.type)+'15'}"&gt;
          &lt;component :is="getMediaIcon(m.type)" :style="{color:getMediaColor(m.type),fontSize:'2rem'}"/&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;span &gt;{{ m.name }}&lt;/span&gt;
          &lt;span &gt;{{ formatFileSize(m.size) }}&lt;/span&gt;
          &lt;span &gt;{{ formatTime(m.created_at) }}&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { PictureOutlined, AudioOutlined, PlaySquareOutlined, FileImageOutlined } from '@ant-design/icons-vue'
import { filesAPI } from '@/api/modules/files_api'
import { useAgentPage } from '@/composables/useAgentPage'
import { message } from 'ant-design-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/media', () =&gt; loadFiles())
const tab = ref('image')
interface MediaFile {
  id: string
  name: string
  type: string
  size: number
  created_at: string
}
const files = ref&lt;MediaFile[]&gt;([])
const loading = ref(false)
const list = computed(() =&gt; {
  return files.value.filter(d =&gt; {
    if (tab.value === 'image') return d.type === 'image' || d.name.match(/\.(png|jpg|jpeg|gif|webp|svg)$/i)
    if (tab.value === 'audio') return d.type === 'audio' || d.name.match(/\.(mp3|wav|ogg|flac|aac)$/i)
    if (tab.value === 'video') return d.type === 'video' || d.name.match(/\.(mp4|webm|mov|avi|mkv)$/i)
    return true
  })
})
const getMediaIcon = (type: string) =&gt; {
  if (type === 'image' || type?.match(/image/)) return FileImageOutlined
  if (type === 'audio' || type?.match(/audio/)) return AudioOutlined
  if (type === 'video' || type?.match(/video/)) return PlaySquareOutlined
  return PictureOutlined
}
const getMediaColor = (type: string) =&gt; {
  if (type === 'image' || type?.match(/image/)) return '#3b82f6'
  if (type === 'audio' || type?.match(/audio/)) return '#8b5cf6'
  if (type === 'video' || type?.match(/video/)) return '#f59e0b'
  return '#06b6d4'
}
const formatFileSize = (bytes: number) =&gt; {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}
const formatTime = (time: string) =&gt; {
  if (!time) return ''
  const d = new Date(time)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const loadFiles = async () =&gt; {
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
onMounted(async () =&gt; {
  await initAgent()
  loadFiles()
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;