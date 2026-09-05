&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;PieChartOutlined :style="{ color: '#8b5cf6' }" /&gt;
        统计概览
      &lt;/h2&gt;
      &lt;div &gt;
        &lt;a-button @click="loadData" :loading="loading"&gt;
          &lt;ReloadOutlined /&gt; 刷新
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;UserOutlined  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ userStats.total_users || 0 }}&lt;/div&gt;
          &lt;div &gt;用户数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;TeamOutlined  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ userStats.total_groups || 0 }}&lt;/div&gt;
          &lt;div &gt;群组数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;RobotOutlined  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ agentStats.total_agents || 0 }}&lt;/div&gt;
          &lt;div &gt;Agent 数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;FileTextOutlined  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ formatNumber(memoryStats.total_memories || 0) }}&lt;/div&gt;
          &lt;div &gt;记忆数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" /&gt;
    &lt;a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
    &lt;div v-if="!loading" &gt;
      &lt;div &gt;
        &lt;h4&gt;&lt;LineChartOutlined /&gt; 每日对话量&lt;/h4&gt;
        &lt;canvas ref="c1" /&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;BarChartOutlined /&gt; Token 消耗分布
        &lt;canvas ref="c2" /&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div  v-if="!loading"&gt;
      &lt;h4&gt;&lt;RobotOutlined /&gt; Agent 统计&lt;/h4&gt;
      &lt;a-table
        :columns="cols"
        :data-source="agentList"
        row-key="agent_id"
        size="middle"
        :pagination="false"
      &gt;
        &lt;template #bodyCell="{ column, record }"&gt;
          &lt;template v-if="column.key === 'is_default'"&gt;
            &lt;a-tag :color="record.is_default ? 'green' : 'default'"&gt;
              {{ record.is_default ? '默认' : '普通' }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'memory_enabled'"&gt;
            &lt;a-tag :color="record.memory_enabled ? 'blue' : 'default'"&gt;
              {{ record.memory_enabled ? '启用' : '禁用' }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
    &lt;div  v-if="!loading &amp;&amp; memoryStats"&gt;
      &lt;h3&gt;&lt;DatabaseOutlined /&gt; 记忆分类统计&lt;/h3&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;div &gt;按分类&lt;/div&gt;
          &lt;div  v-for="(count, cat) in memoryStats.by_category" :key="cat"&gt;
            {{ getCategoryLabel(cat) }}: {{ count }}
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;按情感&lt;/div&gt;
          &lt;div  v-for="(count, emotion) in memoryStats.by_emotion" :key="emotion"&gt;
            {{ emotion }}: {{ count }}
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;按温度&lt;/div&gt;
          &lt;div  v-for="(count, temp) in memoryStats.temperature_distribution" :key="temp"&gt;
            {{ temp }}: {{ count }}
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive, onMounted, nextTick } from 'vue'
import { message } from 'ant-design-vue'
import {
  PieChartOutlined,
  ReloadOutlined,
  UserOutlined,
  TeamOutlined,
  RobotOutlined,
  FileTextOutlined,
  LineChartOutlined,
  BarChartOutlined,
  DatabaseOutlined,
} from '@ant-design/icons-vue'
import { statsAPI } from '@/api/modules/stats'
const loading = ref(false)
const error = ref('')
const userStats = reactive({
  total_users: 0,
  total_groups: 0,
  active_users: 0,
})
const agentStats = reactive({
  total_agents: 0,
  agents: [] as Record&lt;string, unknown&gt;[],
})
const memoryStats = reactive({
  total_memories: 0,
  by_category: {} as Record&lt;string, number&gt;,
  by_emotion: {} as Record&lt;string, number&gt;,
  temperature_distribution: {} as Record&lt;string, number&gt;,
})
interface AgentStat {
  agent_id: string
  is_default?: boolean
  memory_enabled?: boolean
  memory_count?: number
  memory_stats?: { total?: number }
}
const agentList = ref&lt;AgentStat[]&gt;([])
const c1 = ref&lt;HTMLCanvasElement&gt;()
const c2 = ref&lt;HTMLCanvasElement&gt;()
const cols = [
  { title: 'Agent ID', dataIndex: 'agent_id', key: 'agent_id' },
  { title: '类型', dataIndex: 'is_default', key: 'is_default', width: 100 },
  { title: '记忆', dataIndex: 'memory_enabled', key: 'memory_enabled', width: 100 },
  { title: '记忆数', key: 'memory_count', width: 120 },
]
const categoryLabels: Record&lt;string, string&gt; = {
  short_term: '短期记忆',
  long_term: '长期记忆',
  episodic: '情景记忆',
  semantic: '语义记忆',
}
function getCategoryLabel(cat: string) {
  return categoryLabels[cat] || cat
}
function formatNumber(num: number) {
  if (num &gt;= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num &gt;= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}
function barChart(canvas: HTMLCanvasElement | null, color: string, data: number[]) {
  if (!canvas) return
  const ctx = canvas.getContext('2d')!
  const dpr = devicePixelRatio || 1
  const r = canvas.getBoundingClientRect()
  canvas.width = r.width * dpr
  canvas.height = r.height * dpr
  ctx.scale(dpr, dpr)
  const w = r.width,
    h = r.height,
    barW = Math.min(40, (w - 80) / data.length),
    gap = 8
  const max = Math.max(...data)
  ctx.clearRect(0, 0, w, h)
  data.forEach((v, i) =&gt; {
    const x = 40 + i * (barW + gap),
      y = h - 20 - (v / max) * (h - 50),
      bh = (v / max) * (h - 50)
    ctx.fillStyle = color + '50'
    roundRect(ctx, x, y, barW, bh, 4)
    ctx.fillStyle = color
    roundRect(ctx, x, y + (v &lt; max * 0.2 ? bh - 2 : 2), barW, v &lt; max * 0.2 ? 2 : bh - 2, 4)
  })
  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'center'
  data.forEach((v, i) =&gt; ctx.fillText(v.toString(), 40 + i * (barW + gap) + barW / 2, h - 5))
}
function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
  ctx.fill()
}
async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const [userRes, agentRes, memoryRes] = await Promise.all([
      statsAPI.getUserStats().catch(() =&gt; ({ data: null })),
      statsAPI.getAgentsStats().catch(() =&gt; ({ data: null })),
      statsAPI.getMemoryStats().catch(() =&gt; ({ data: null })),
    ])
    if (userRes.data) {
      Object.assign(userStats, userRes.data)
    }
    if (agentRes.data) {
      Object.assign(agentStats, agentRes.data)
      agentList.value = agentRes.data.agents || []
      agentList.value.forEach((agent) =&gt; {
        agent.memory_count = agent.memory_stats?.total || 0
      })
    }
    if (memoryRes.data) {
      Object.assign(memoryStats, memoryRes.data)
    }
    await nextTick()
    barChart(c1.value, '#3b82f6', [89, 67, 30, 55, 42, 78, 92])
    barChart(c2.value, '#a78bfa', [890, 670, 340, 1200, 560, 980, 740])
  } catch (e: unknown) {
    const err = e as { message?: string }
    error.value = err?.message || '加载统计数据失败'
    message.error('加载统计数据失败')
  } finally {
    loading.value = false
  }
}
onMounted(() =&gt; {
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 24px;
}
.hd {
  padding: 14px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hd-actions {
  display: flex;
  gap: 8px;
}
.t {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sr {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.s {
  flex: 1;
  padding: 14px 18px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.s-icon {
  font-size: 2rem;
  color: #8b5cf6;
}
.s-info {
  flex: 1;
}
.s-num {
  font-size: 1.4rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.s-label {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.chart {
  padding: 16px 20px;
  border-radius: 12px;
}
.chart h4 {
  color: #e2e8f0;
  margin: 0 0 10px;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 8px;
}
.chart canvas {
  width: 100%;
  height: 180px;
}
.tb {
  padding: 20px;
  border-radius: 12px;
}
.tb h4 {
  color: #e2e8f0;
  margin: 0 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section {
  padding: 20px;
  border-radius: 12px;
}
.section h3 {
  color: #e2e8f0;
  margin: 0 0 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.stat-item {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  padding: 12px;
}
.stat-label {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin-bottom: 8px;
}
.stat-value {
  font-size: 0.8rem;
  color: #e2e8f0;
  padding: 4px 0;
  font-family: monospace;
}
@media (max-width: 768px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .sr {
    grid-template-columns: repeat(2, 1fr);
  }
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
&lt;/style&gt;
&nbsp;