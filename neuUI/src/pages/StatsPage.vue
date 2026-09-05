<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t">
        <PieChartOutlined :style="{ color: '#8b5cf6' }" />
        统计概览
      </h2>
      <div class="hd-actions">
        <a-button @click="loadData" :loading="loading">
          <ReloadOutlined /> 刷新
        </a-button>
      </div>
    </div>

    <div class="sr">
      <div class="s glass-effect">
        <UserOutlined class="s-icon" />
        <div class="s-info">
          <div class="s-num">{{ userStats.total_users || 0 }}</div>
          <div class="s-label">用户数</div>
        </div>
      </div>
      <div class="s glass-effect">
        <TeamOutlined class="s-icon" />
        <div class="s-info">
          <div class="s-num">{{ userStats.total_groups || 0 }}</div>
          <div class="s-label">群组数</div>
        </div>
      </div>
      <div class="s glass-effect">
        <RobotOutlined class="s-icon" />
        <div class="s-info">
          <div class="s-num">{{ agentStats.total_agents || 0 }}</div>
          <div class="s-label">Agent 数</div>
        </div>
      </div>
      <div class="s glass-effect">
        <FileTextOutlined class="s-icon" />
        <div class="s-info">
          <div class="s-num">{{ formatNumber(memoryStats.total_memories || 0) }}</div>
          <div class="s-label">记忆数</div>
        </div>
      </div>
    </div>

    <a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" />
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />

    <div v-if="!loading" class="grid">
      <div class="chart glass-effect">
        <h4><LineChartOutlined /> 每日对话量</h4>
        <canvas ref="c1" />
      </div>
      <div class="chart glass-effect">
        <BarChartOutlined /> Token 消耗分布
        <canvas ref="c2" />
      </div>
    </div>

    <div class="tb glass-effect" v-if="!loading">
      <h4><RobotOutlined /> Agent 统计</h4>
      <a-table
        :columns="cols"
        :data-source="agentList"
        row-key="agent_id"
        size="middle"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'is_default'">
            <a-tag :color="record.is_default ? 'green' : 'default'">
              {{ record.is_default ? '默认' : '普通' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'memory_enabled'">
            <a-tag :color="record.memory_enabled ? 'blue' : 'default'">
              {{ record.memory_enabled ? '启用' : '禁用' }}
            </a-tag>
          </template>
        </template>
      </a-table>
    </div>

    <div class="section glass-effect" v-if="!loading && memoryStats">
      <h3><DatabaseOutlined /> 记忆分类统计</h3>
      <div class="stats-grid">
        <div class="stat-item">
          <div class="stat-label">按分类</div>
          <div class="stat-value" v-for="(count, cat) in memoryStats.by_category" :key="cat">
            {{ getCategoryLabel(cat) }}: {{ count }}
          </div>
        </div>
        <div class="stat-item">
          <div class="stat-label">按情感</div>
          <div class="stat-value" v-for="(count, emotion) in memoryStats.by_emotion" :key="emotion">
            {{ emotion }}: {{ count }}
          </div>
        </div>
        <div class="stat-item">
          <div class="stat-label">按温度</div>
          <div class="stat-value" v-for="(count, temp) in memoryStats.temperature_distribution" :key="temp">
            {{ temp }}: {{ count }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
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
  agents: [] as Record<string, unknown>[],
})

const memoryStats = reactive({
  total_memories: 0,
  by_category: {} as Record<string, number>,
  by_emotion: {} as Record<string, number>,
  temperature_distribution: {} as Record<string, number>,
})

interface AgentStat {
  agent_id: string
  is_default?: boolean
  memory_enabled?: boolean
  memory_count?: number
  memory_stats?: { total?: number }
}

const agentList = ref<AgentStat[]>([])
const c1 = ref<HTMLCanvasElement>()
const c2 = ref<HTMLCanvasElement>()

const cols = [
  { title: 'Agent ID', dataIndex: 'agent_id', key: 'agent_id' },
  { title: '类型', dataIndex: 'is_default', key: 'is_default', width: 100 },
  { title: '记忆', dataIndex: 'memory_enabled', key: 'memory_enabled', width: 100 },
  { title: '记忆数', key: 'memory_count', width: 120 },
]

const categoryLabels: Record<string, string> = {
  short_term: '短期记忆',
  long_term: '长期记忆',
  episodic: '情景记忆',
  semantic: '语义记忆',
}

function getCategoryLabel(cat: string) {
  return categoryLabels[cat] || cat
}

function formatNumber(num: number) {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
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
  data.forEach((v, i) => {
    const x = 40 + i * (barW + gap),
      y = h - 20 - (v / max) * (h - 50),
      bh = (v / max) * (h - 50)
    ctx.fillStyle = color + '50'
    roundRect(ctx, x, y, barW, bh, 4)
    ctx.fillStyle = color
    roundRect(ctx, x, y + (v < max * 0.2 ? bh - 2 : 2), barW, v < max * 0.2 ? 2 : bh - 2, 4)
  })
  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'center'
  data.forEach((v, i) => ctx.fillText(v.toString(), 40 + i * (barW + gap) + barW / 2, h - 5))
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
      statsAPI.getUserStats().catch(() => ({ data: null })),
      statsAPI.getAgentsStats().catch(() => ({ data: null })),
      statsAPI.getMemoryStats().catch(() => ({ data: null })),
    ])

    if (userRes.data) {
      Object.assign(userStats, userRes.data)
    }

    if (agentRes.data) {
      Object.assign(agentStats, agentRes.data)
      agentList.value = agentRes.data.agents || []
      agentList.value.forEach((agent) => {
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

onMounted(() => {
  loadData()
})
</script>

<style scoped>
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
</style>
