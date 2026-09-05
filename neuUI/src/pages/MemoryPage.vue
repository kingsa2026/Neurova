<template>
  <div class="memory-page">
    <div class="page-header glass-effect">
      <h2 class="page-title"><Database class="page-icon" /> 记忆管理</h2>
      <div class="header-right">
        <a-select v-model:value="agentId" style="width:200px" :options="agentOptions" placeholder="选择 Agent" @change="loadMemories" allow-clear />
        <a-input-search v-model:value="search" placeholder="搜索记忆..." style="width:260px" />
      </div>
    </div>
    <a-alert v-if="memError" :message="memError" type="error" show-icon closable />

    <!-- 分类标签页 - 使用后端标准分类 -->
    <a-tabs v-model:activeKey="tab" class="glass-effect memory-tabs" @change="handleTabChange">
      <a-tab-pane key="all" tab="全部" />
      <a-tab-pane key="conversation" tab="对话" />
      <a-tab-pane key="fact" tab="事实" />
      <a-tab-pane key="profile" tab="用户画像" />
      <a-tab-pane key="experience" tab="经验" />
      <a-tab-pane key="lesson" tab="教训" />
      <a-tab-pane key="task" tab="任务" />
      <a-tab-pane key="emotional" tab="情感" />
      <a-tab-pane key="skill" tab="技能" />
      <a-tab-pane key="creative" tab="创意" />
      <a-tab-pane key="identity" tab="身份" />
    </a-tabs>

    <div class="stats-row">
      <div class="stat-mini glass-effect"><span>总计</span><b>{{ filtered.length }}</b></div>
      <div class="stat-mini glass-effect"><span>今日新增</span><b class="accent">{{ today }}</b></div>
    </div>

    <!-- 使用统一的 MemoryTimeline 组件 -->
    <div class="timeline-section glass-effect" v-if="filtered.length">
      <MemoryTimeline :memories="filtered" />
    </div>
    <div v-else class="glass-effect" style="text-align:center;padding:64px 0;color:rgba(255,255,255,0.3)">暂无记忆数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Database } from '@lucide/vue'
import { memoryAPI } from '@/api/modules/memory'
import { useAgentPage } from '@/composables/useAgentPage'
import MemoryTimeline from '@/components/MemoryTimeline.vue'

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/memory', () => loadMemories())
const agentOptions = computed(() => agentStore.agentOptions)

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

const memories = ref<MemoryItem[]>([])

const filtered = computed(() => {
  let list = memories.value
  
  // 按分类过滤
  if (tab.value !== 'all') {
    list = list.filter(m => m.category === tab.value || m.type === tab.value)
  }
  
  // 按搜索词过滤
  if (search.value) {
    const keyword = search.value.toLowerCase()
    list = list.filter(m => 
      (m.summary && m.summary.toLowerCase().includes(keyword)) ||
      (m.content && m.content.toLowerCase().includes(keyword))
    )
  }
  
  return list
})

const today = computed(() => {
  const now = Date.now()
  const todayStart = new Date()
  todayStart.setHours(0, 0, 0, 0)
  return memories.value.filter(m => m.timestamp >= todayStart.getTime()).length
})

function handleTabChange() {
  // 可以在这里添加额外的逻辑
}

function formatTime(ts: number) {
  const diff = Date.now() - ts
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff/60000)+'分钟前'
  if (diff < 86400000) return Math.floor(diff/3600000)+'小时前'
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
      memories.value = list.map((m: Record<string, unknown>) => ({
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

onMounted(async () => {
  await initAgent()
  loadMemories()
})
</script>

<style scoped>
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
</style>
