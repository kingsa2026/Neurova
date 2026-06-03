&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;Database  /&gt; 记忆管理&lt;/h2&gt;
      &lt;div &gt;
        &lt;a-select v-model:value="agentId" style="width:200px" :options="agentOptions" placeholder="选择 Agent" @change="loadMemories" allow-clear /&gt;
        &lt;a-input-search v-model:value="search" placeholder="搜索记忆..." style="width:260px" /&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-alert v-if="memError" :message="memError" type="error" show-icon closable /&gt;
    &lt;!-- 分类标签页 - 使用后端标准分类 --&gt;
    &lt;a-tabs v-model:activeKey="tab"  @change="handleTabChange"&gt;
      &lt;a-tab-pane key="all" tab="全部" /&gt;
      &lt;a-tab-pane key="conversation" tab="对话" /&gt;
      &lt;a-tab-pane key="fact" tab="事实" /&gt;
      &lt;a-tab-pane key="profile" tab="用户画像" /&gt;
      &lt;a-tab-pane key="experience" tab="经验" /&gt;
      &lt;a-tab-pane key="lesson" tab="教训" /&gt;
      &lt;a-tab-pane key="task" tab="任务" /&gt;
      &lt;a-tab-pane key="emotional" tab="情感" /&gt;
      &lt;a-tab-pane key="skill" tab="技能" /&gt;
      &lt;a-tab-pane key="creative" tab="创意" /&gt;
      &lt;a-tab-pane key="identity" tab="身份" /&gt;
    &lt;/a-tabs&gt;
    &lt;div &gt;
      &lt;div &gt;&lt;span&gt;总计&lt;/span&gt;&lt;b&gt;{{ filtered.length }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;&lt;span&gt;今日新增&lt;/span&gt;&lt;b &gt;{{ today }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 使用统一的 MemoryTimeline 组件 --&gt;
    &lt;div  v-if="filtered.length"&gt;
      &lt;MemoryTimeline :memories="filtered" /&gt;
    &lt;/div&gt;
    &lt;div v-else  style="text-align:center;padding:64px 0;color:rgba(255,255,255,0.3)"&gt;暂无记忆数据&lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { Database } from '@lucide/vue'
import { memoryAPI } from '@/api/modules/memory'
import { useAgentPage } from '@/composables/useAgentPage'
import MemoryTimeline from '@/components/MemoryTimeline.vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/memory', () =&gt; loadMemories())
const agentOptions = computed(() =&gt; agentStore.agentOptions)
const tab = ref('all')
const search = ref('')
interface MemoryItem {
  id: string
  category: string
  type: string
  content: string
  summary: string
  timestamp: number
  tags: string[]
  importance: number
}
const memories = ref&lt;MemoryItem[]&gt;([])
const filtered = computed(() =&gt; {
  let list = memories.value
  // 按分类过滤
  if (tab.value !== 'all') {
    list = list.filter(m =&gt; m.category === tab.value || m.type === tab.value)
  }
  // 按搜索词过滤
  if (search.value) {
    const keyword = search.value.toLowerCase()
    list = list.filter(m =&gt; 
      (m.summary &amp;&amp; m.summary.toLowerCase().includes(keyword)) ||
      (m.content &amp;&amp; m.content.toLowerCase().includes(keyword))
    )
  }
  return list
})
const today = computed(() =&gt; {
  const now = Date.now()
  const todayStart = new Date()
  todayStart.setHours(0, 0, 0, 0)
  return memories.value.filter(m =&gt; m.timestamp &gt;= todayStart.getTime()).length
})
function handleTabChange() {
  // 可以在这里添加额外的逻辑
}
function formatTime(ts: number) {
  const diff = Date.now() - ts
  if (diff &lt; 60000) return '刚刚'
  if (diff &lt; 3600000) return Math.floor(diff/60000)+'分钟前'
  if (diff &lt; 86400000) return Math.floor(diff/3600000)+'小时前'
  return Math.floor(diff/86400000)+'天前'
}
const memLoading = ref(false)
const memError = ref('')
async function loadMemories() {
  memLoading.value = true
  memError.value = ''
  try {
    const res = await memoryAPI.list(agentId.value || undefined)
    // 后端返回 { code: 0, data: { count, memories: [...] } }
    const list = (res as { data?: { memories?: unknown[] } })?.data?.memories
    if (Array.isArray(list)) {
      memories.value = list.map((m: Record&lt;string, unknown&gt;) =&gt; ({
        id: (m.id as string) || String(Date.now()),
        // 统一使用 category 字段（后端标准），兼容 type 字段
        category: (m.category as string) || (m.type as string) || 'conversation',
        type: (m.type as string) || (m.category as string) || 'conversation', // 兼容两种字段名
        content: (m.content as string) || (m.summary as string) || '',
        summary: (m.summary as string) || (m.content as string) || '',
        timestamp: typeof m.timestamp === 'number' ? m.timestamp :
                  typeof m.created_at === 'string' ? new Date(m.created_at as string).getTime() :
                  Date.now(),
        tags: (Array.isArray(m.tags) ? m.tags : []) as string[],
        importance: typeof m.importance === 'number' ? m.importance : 0.5,
      }))
    } else {
      memError.value = (res as { message?: string })?.message || '获取记忆失败'
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { message?: string } }; message?: string }
    memError.value = err?.response?.data?.message || err?.message || '网络请求失败'
  } finally {
    memLoading.value = false
  }
}
onMounted(async () =&gt; {
  await initAgent()
  loadMemories()
})
&lt;/script&gt;
&lt;style scoped&gt;
.memory-page { display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;flex-wrap:wrap;gap:10px; }
.page-title { font-size:1.25rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px; }
.page-icon { width:24px;height:24px;color:#60a5fa; }
.header-right { display:flex;align-items:center;gap:10px; }
.memory-tabs { padding:0 16px;border-radius:12px; }
.stats-row { display:flex;gap:12px; }
.stat-mini { flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:0.85rem; }
.stat-mini b { font-size:1.5rem;color:#e2e8f0; }
.stat-mini .accent { color:#60a5fa; }
.timeline-section { padding:24px;border-radius:12px; }
&lt;/style&gt;
&nbsp;