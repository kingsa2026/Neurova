<template>
  <div >
    <div >
      <h2 ><TeamOutlined :style="{color:'#3b82f6'}"/> 协作中心</h2>
    </div>
    <!-- 统计卡片 -->
    <div >
      <div >
        协作<b >{{ stats.collaborations || 0 }}</b>
      </div>
      <div >
        Agent<b >{{ stats.agents || 0 }}</b>
      </div>
      <div >
        模板<b >{{ stats.templates || 0 }}</b>
      </div>
    </div>
    <!-- 加载状态 -->
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />
    <!-- 主内容区 -->
    <div  v-else>
      <!-- 能力矩阵卡片 -->
      <div >
        <h3>能力矩阵</h3>
        <a-table
          :columns="mcols"
          :data-source="matrixData"
          row-key="agent"
          size="middle"
          :pagination="false"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key!=='agent'">
              <div >
                <div  :style="{width:record[column.key]*10+'%',background:getCapabilityColor(record[column.key])}"/>
                <span>{{ record[column.key] }}/10</span>
              </div>
            </template>
          </template>
        </a-table>
      </div>
      <!-- 侧边栏 -->
      <div >
        <div  v-for="e in entries" :key="e.path" @click="$router.push(e.path)">
          <div :style="{background:e.c+'15',color:e.c}" >
            <component :is="e.icon"/>
          </div>
          <div>
            <span >{{ e.label }}</span>
            <span >{{ e.desc }}</span>
          </div>
        </div>
        <!-- 死信队列统计 -->
        <div  v-if="dlqStats">
          <h4>死信队列</h4>
          <div >
            <span>消息数</span>
            <b>{{ dlqStats.message_count }}</b>
          </div>
          <div >
            <span>平均延迟</span>
            <b>{{ dlqStats.avg_delay_seconds }}s</b>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { TeamOutlined, AppstoreOutlined, PlusOutlined, HistoryOutlined } from '@ant-design/icons-vue'
import { collaborationAPI } from '@/api/modules/collaboration'
const loading = ref(false)
const stats = ref({ collaborations: 0, agents: 0, templates: 0 })
interface MatrixRow {
  agent: string
  chat: number
  search: number
  doc: number
  code: number
  analytics: number
}
const matrixData = ref<MatrixRow[]>([])
interface DlqStats {
  message_count: number
  avg_delay_seconds: number
}
const dlqStats = ref<DlqStats | null>(null)
const mcols = [
  { title: 'Agent', dataIndex: 'agent', key: 'agent' },
  { title: '对话', key: 'chat' },
  { title: '搜索', key: 'search' },
  { title: '文档', key: 'doc' },
  { title: '代码', key: 'code' },
  { title: '分析', key: 'analytics' }
]
const entries = [
  { path: '/collaboration/templates', label: '模板库', desc: '查看模板', c: '#3b82f6', icon: AppstoreOutlined },
  { path: '/collaboration/initiate', label: '发起协作', desc: '创建新协作', c: '#8b5cf6', icon: PlusOutlined },
  { path: '/collaboration/history', label: '历史记录', desc: '查看过往', c: '#34d399', icon: HistoryOutlined }
]
const getCapabilityColor = (level: number) => {
  if (level >= 8) return '#34d399'
  if (level >= 6) return '#fbbf24'
  return '#ef4444'
}
const loadData = async () => {
  loading.value = true
  try {
    // 并行加载多个API
    const [matrixRes, capabilitiesRes, templatesRes, dlqRes] = await Promise.allSettled([
      collaborationAPI.getMatrix(),
      collaborationAPI.getCapabilities(),
      collaborationAPI.getTemplates(),
      collaborationAPI.getDlqStats()
    ])
    // 处理能力矩阵
    if (matrixRes.status === 'fulfilled' && matrixRes.value?.data) {
      const data = matrixRes.value.data
      if (data.matrix) {
        matrixData.value = Object.entries(data.matrix).map(([agent, caps]: [string, Record<string, number>]) => ({
          agent,
          chat: caps.chat || 5,
          search: caps.search || 5,
          doc: caps.doc || 5,
          code: caps.code || 5,
          analytics: caps.analytics || 5
        }))
      }
    }
    // 处理能力列表
    if (capabilitiesRes.status === 'fulfilled' && capabilitiesRes.value?.data) {
      const data = capabilitiesRes.value.data
      stats.value.agents = Array.isArray(data.capabilities) ? data.capabilities.length : 0
    }
    // 处理模板列表
    if (templatesRes.status === 'fulfilled' && templatesRes.value?.data) {
      const data = templatesRes.value.data
      stats.value.templates = Array.isArray(data.templates) ? data.templates.length : 0
    }
    // 处理死信队列
    if (dlqRes.status === 'fulfilled' && dlqRes.value?.data) {
      dlqStats.value = dlqRes.value.data
    }
  } catch (err) {
    console.error('加载协作数据失败', err)
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  loadData()
})
</script>
<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: 0.85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #3b82f6; }
.body { display: grid; grid-template-columns: 1fr 240px; gap: 14px; }
.card { padding: 20px; border-radius: 12px; }
.card h3 { color: #e2e8f0; margin: 0 0 12px; }
.bar { display: flex; align-items: center; gap: 6px; max-width: 100px; }
.bf { height: 6px; border-radius: 3px; min-width: 20px; transition: width 0.3s; }
.bar span { color: rgba(255,255,255,0.3); font-size: 0.78rem; }
.side { display: flex; flex-direction: column; gap: 10px; }
.entry { padding: 16px; border-radius: 10px; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: transform 0.2s; }
.entry:hover { transform: translateX(4px); }
.ei { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 1.1rem; }
.el { color: #e2e8f0; font-size: 0.85rem; display: block; }
.ed { color: rgba(255,255,255,0.3); font-size: 0.72rem; }
.dlq { padding: 16px; border-radius: 10px; }
.dlq h4 { color: #e2e8f0; margin: 0 0 10px; font-size: 0.9rem; }
.dlq-stat { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 0.8rem; }
.dlq-stat span { color: rgba(255,255,255,0.4); }
.dlq-stat b { color: #f59e0b; }
@media (max-width: 900px) { .body { grid-template-columns: 1fr } }
</style>
 