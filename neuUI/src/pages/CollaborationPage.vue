&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;TeamOutlined :style="{color:'#3b82f6'}"/&gt; 协作中心&lt;/h2&gt;
    &lt;/div&gt;
    &lt;!-- 统计卡片 --&gt;
    &lt;div &gt;
      &lt;div &gt;
        协作&lt;b &gt;{{ stats.collaborations || 0 }}&lt;/b&gt;
      &lt;/div&gt;
      &lt;div &gt;
        Agent&lt;b &gt;{{ stats.agents || 0 }}&lt;/b&gt;
      &lt;/div&gt;
      &lt;div &gt;
        模板&lt;b &gt;{{ stats.templates || 0 }}&lt;/b&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 加载状态 --&gt;
    &lt;a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
    &lt;!-- 主内容区 --&gt;
    &lt;div  v-else&gt;
      &lt;!-- 能力矩阵卡片 --&gt;
      &lt;div &gt;
        &lt;h3&gt;能力矩阵&lt;/h3&gt;
        &lt;a-table
          :columns="mcols"
          :data-source="matrixData"
          row-key="agent"
          size="middle"
          :pagination="false"
        &gt;
          &lt;template #bodyCell="{ column, record }"&gt;
            &lt;template v-if="column.key!=='agent'"&gt;
              &lt;div &gt;
                &lt;div  :style="{width:record[column.key]*10+'%',background:getCapabilityColor(record[column.key])}"/&gt;
                &lt;span&gt;{{ record[column.key] }}/10&lt;/span&gt;
              &lt;/div&gt;
            &lt;/template&gt;
          &lt;/template&gt;
        &lt;/a-table&gt;
      &lt;/div&gt;
      &lt;!-- 侧边栏 --&gt;
      &lt;div &gt;
        &lt;div  v-for="e in entries" :key="e.path" @click="$router.push(e.path)"&gt;
          &lt;div :style="{background:e.c+'15',color:e.c}" &gt;
            &lt;component :is="e.icon"/&gt;
          &lt;/div&gt;
          &lt;div&gt;
            &lt;span &gt;{{ e.label }}&lt;/span&gt;
            &lt;span &gt;{{ e.desc }}&lt;/span&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;!-- 死信队列统计 --&gt;
        &lt;div  v-if="dlqStats"&gt;
          &lt;h4&gt;死信队列&lt;/h4&gt;
          &lt;div &gt;
            &lt;span&gt;消息数&lt;/span&gt;
            &lt;b&gt;{{ dlqStats.message_count }}&lt;/b&gt;
          &lt;/div&gt;
          &lt;div &gt;
            &lt;span&gt;平均延迟&lt;/span&gt;
            &lt;b&gt;{{ dlqStats.avg_delay_seconds }}s&lt;/b&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
const matrixData = ref&lt;MatrixRow[]&gt;([])
interface DlqStats {
  message_count: number
  avg_delay_seconds: number
}
const dlqStats = ref&lt;DlqStats | null&gt;(null)
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
const getCapabilityColor = (level: number) =&gt; {
  if (level &gt;= 8) return '#34d399'
  if (level &gt;= 6) return '#fbbf24'
  return '#ef4444'
}
const loadData = async () =&gt; {
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
    if (matrixRes.status === 'fulfilled' &amp;&amp; matrixRes.value?.data) {
      const data = matrixRes.value.data
      if (data.matrix) {
        matrixData.value = Object.entries(data.matrix).map(([agent, caps]: [string, Record&lt;string, number&gt;]) =&gt; ({
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
    if (capabilitiesRes.status === 'fulfilled' &amp;&amp; capabilitiesRes.value?.data) {
      const data = capabilitiesRes.value.data
      stats.value.agents = Array.isArray(data.capabilities) ? data.capabilities.length : 0
    }
    // 处理模板列表
    if (templatesRes.status === 'fulfilled' &amp;&amp; templatesRes.value?.data) {
      const data = templatesRes.value.data
      stats.value.templates = Array.isArray(data.templates) ? data.templates.length : 0
    }
    // 处理死信队列
    if (dlqRes.status === 'fulfilled' &amp;&amp; dlqRes.value?.data) {
      dlqStats.value = dlqRes.value.data
    }
  } catch (err) {
    console.error('加载协作数据失败', err)
  } finally {
    loading.value = false
  }
}
onMounted(() =&gt; {
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;