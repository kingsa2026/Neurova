<template>
  <div class="dashboard-page">
    <!-- 欢迎区域 -->
    <div class="welcome-section glass-effect">
      <div class="welcome-left">
        <h1 class="welcome-title">
          你好，{{ username }}
          <span class="welcome-wave">👋</span>
        </h1>
        <p class="welcome-sub">欢迎回到 Neurova 智能平台 · {{ formattedDate }}</p>
        <a-alert v-if="dashError" :message="dashError" type="error" show-icon closable style="margin-top:8px" />
      </div>
      <div class="welcome-right">
        <div class="quick-badge" @click="$router.push('/agents/create')">
          <PlusOutlined /> 新建 Agent
        </div>
        <div class="quick-badge" @click="$router.push('/chat')">
          <MessageOutlined /> 开始对话
        </div>
      </div>
    </div>

    <!-- 统计卡片行 -->
    <div class="stat-row">
      <div
        v-for="stat in stats"
        :key="stat.key"
        class="stat-card glass-effect"
        :style="{ '--accent': stat.color }"
      >
        <div class="stat-card__icon">
          <component :is="stat.icon" />
        </div>
        <div class="stat-card__content">
          <span class="stat-card__label">{{ stat.label }}</span>
          <span class="stat-card__value">{{ stat.value }}</span>
          <span class="stat-card__trend">
            <CaretUpOutlined v-if="stat.trend > 0" class="trend-up" />
            <CaretDownOutlined v-else class="trend-down" />
            {{ Math.abs(stat.trend) }}% vs 上周
          </span>
        </div>
      </div>
    </div>

    <!-- 主内容行 -->
    <div class="main-row">
      <!-- 左侧：图表 + 快捷操作 -->
      <div class="main-left">
        <!-- Token 消耗趋势图表 -->
        <div class="chart-card glass-effect">
          <div class="chart-header">
            <h3>Token 消耗趋势</h3>
            <a-radio-group v-model:value="chartRange" size="small">
              <a-radio-button value="7d">7 天</a-radio-button>
              <a-radio-button value="30d">30 天</a-radio-button>
            </a-radio-group>
          </div>
          <div class="chart-container">
            <canvas ref="tokenChartRef" class="token-chart"></canvas>
          </div>
        </div>

        <!-- 快捷操作 -->
        <div class="actions-card glass-effect">
          <h3>快捷操作</h3>
          <div class="action-grid">
            <div class="action-item" v-for="a in quickActions" :key="a.key" @click="$router.push(a.path)">
              <div class="action-item__icon" :style="{ background: a.color + '18', color: a.color }">
                <component :is="a.icon" />
              </div>
              <span class="action-item__label">{{ a.label }}</span>
              <span class="action-item__desc">{{ a.desc }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：最近动态 + 系统状态 -->
      <div class="main-right">
        <!-- 最近动态 -->
        <div class="recent-card glass-effect">
          <h3>最近动态</h3>
          <div class="recent-list" v-if="recentActivities.length > 0">
            <div class="recent-item" v-for="item in recentActivities" :key="item.id">
              <div class="recent-item__dot" :style="{ background: item.color }"></div>
              <div class="recent-item__content">
                <span class="recent-item__title">{{ item.title }}</span>
                <span class="recent-item__time">{{ item.time }}</span>
              </div>
            </div>
          </div>
          <div class="recent-empty" v-else>
            <HistoryOutlined class="empty-icon" />
            <span>暂无最近动态</span>
          </div>
        </div>

        <!-- 系统状态 -->
        <div class="status-card glass-effect">
          <h3>系统状态</h3>
          <div class="status-list">
            <div class="status-item">
              <span class="status-item__label">API 服务</span>
              <a-badge status="processing" text="运行中" />
            </div>
            <div class="status-item">
              <span class="status-item__label">LLM 引擎</span>
              <a-badge status="processing" text="就绪" />
            </div>
            <div class="status-item">
              <span class="status-item__label">记忆系统</span>
              <a-badge status="processing" text="正常" />
            </div>
            <div class="status-item">
              <span class="status-item__label">技能引擎</span>
              <a-badge status="default" text="空闲" />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import {
  RobotOutlined,
  MessageOutlined,
  ThunderboltOutlined,
  ApiOutlined,
  PlusOutlined,
  CaretUpOutlined,
  CaretDownOutlined,
  HistoryOutlined,
  DashboardOutlined,
  SettingOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  SearchOutlined,
  BarChartOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'

import { dashboardAPI } from '@/api/modules/dashboard'

const authStore = useAuthStore()
const username = computed(() => authStore.currentUser?.username || '用户')

const dashLoading = ref(false)
const dashError = ref('')

// 获取真实数据
const trendData = ref<number[]>([])
const recentItems = ref<Record<string, unknown>[]>([])

onMounted(async () => {
  dashLoading.value = true
  try {
    const [homeRes, trendsRes, statsRes] = await Promise.allSettled([
      dashboardAPI.getHomeData(),
      dashboardAPI.getTrends(chartRange.value === '7d' ? 7 : 30),
      dashboardAPI.getSystemStats(),
    ])

    if (homeRes.status === 'fulfilled' && homeRes.value?.success && homeRes.value.data) {
      const d = homeRes.value.data
      if (d.stats) {
        stats.value[0].value = d.stats.agent_count ?? stats.value[0].value
        stats.value[1].value = d.stats.conversation_count ?? stats.value[1].value
        if (d.stats.token_count) stats.value[2].value = d.stats.token_count
        if (d.stats.llm_calls) stats.value[3].value = d.stats.llm_calls
        if (d.stats.agent_trend != null) stats.value[0].trend = d.stats.agent_trend
        if (d.stats.conversation_trend != null) stats.value[1].trend = d.stats.conversation_trend
        if (d.stats.token_trend != null) stats.value[2].trend = d.stats.token_trend
        if (d.stats.llm_trend != null) stats.value[3].trend = d.stats.llm_trend
      }
      // 最近动态
      if (d.recent_activities?.length) {
        recentActivities.length = 0
        d.recent_activities.forEach((a: Record<string, unknown>) => recentActivities.push({
          id: a.id, title: a.title || a.description, time: a.time || a.relative_time, color: a.color || '#60a5fa'
        }))
      }
    } else if (homeRes.status === 'fulfilled') {
      dashError.value = homeRes.value?.message || '获取数据失败'
    }

    if (trendsRes.status === 'fulfilled' && trendsRes.value?.success && trendsRes.value.data?.values) {
      trendData.value = trendsRes.value.data.values
    }

    if (statsRes.status === 'fulfilled' && statsRes.value?.success && statsRes.value.data) {
      const sd = statsRes.value.data
      if (sd.agent_count != null) stats.value[0].value = sd.agent_count
      if (sd.memory_count != null) stats.value[1].value = sd.memory_count
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { message?: string } }; message?: string }
    dashError.value = err?.response?.data?.message || err?.message || '网络请求失败'
  } finally {
    dashLoading.value = false
  }

  // 绘制图表（在数据加载完成后）
  await nextTick()
  drawChart()
  window.addEventListener('resize', drawChart)
})

const formattedDate = computed(() => {
  const d = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六']
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 · 星期${week[d.getDay()]}`
})

// ─── 统计数据 ───
const stats = ref([
  { key: 'agents', label: 'Agent 数量', value: 12 as number|string, trend: 20, color: '#60a5fa', icon: RobotOutlined },
  { key: 'conversations', label: '对话次数', value: 186 as number|string, trend: 15, color: '#a78bfa', icon: MessageOutlined },
  { key: 'tokens', label: 'Token 消耗', value: '1.2M' as number|string, trend: 8, color: '#34d399', icon: ThunderboltOutlined },
  { key: 'calls', label: 'LLM 调用', value: 2048 as number|string, trend: -3, color: '#fbbf24', icon: ApiOutlined },
])

// ─── 快捷操作 ───
const quickActions = [
  { key: 'create', label: '新建 Agent', desc: '创建智能助手', path: '/agents/create', icon: PlusOutlined, color: '#60a5fa' },
  { key: 'chat', label: '开始对话', desc: '开始 AI 对话', path: '/chat', icon: MessageOutlined, color: '#a78bfa' },
  { key: 'dashboard', label: '查看分析', desc: '数据统计报告', path: '/analytics', icon: BarChartOutlined, color: '#34d399' },
  { key: 'knowledge', label: '知识库', desc: '管理知识文档', path: '/knowledge', icon: FolderOpenOutlined, color: '#fbbf24' },
  { key: 'memory', label: '记忆管理', desc: '查看记忆数据', path: '/agent/default/memory', icon: DatabaseOutlined, color: '#fb7185' },
  { key: 'settings', label: '系统设置', desc: '配置个性化', path: '/settings', icon: SettingOutlined, color: '#94a3b8' },
]

// ─── 最近动态 ───
const recentActivities = [
  { id: 1, title: 'Agent "智能助手" 完成对话任务', time: '10 分钟前', color: '#60a5fa' },
  { id: 2, title: '新增 32 条向量记忆', time: '1 小时前', color: '#a78bfa' },
  { id: 3, title: '技能 "文本摘要" 已安装', time: '3 小时前', color: '#34d399' },
  { id: 4, title: '知识库 "项目文档" 已更新', time: '昨天', color: '#fbbf24' },
  { id: 5, title: 'Token 消耗达到日限额 80%', time: '昨天', color: '#fb7185' },
]

// ─── Canvas 图表 ───
const tokenChartRef = ref<HTMLCanvasElement>()
const chartRange = ref('7d')
let chartAnimationId = 0

// 图表范围切换 → 重新加载趋势数据
watch(chartRange, async (range) => {
  try {
    const res = await dashboardAPI.getTrends(range === '7d' ? 7 : 30)
    if (res?.success && res.data?.values) {
      trendData.value = res.data.values
      await nextTick(); drawChart()
    }
  } catch { /* ignore */ }
})

function drawChart() {
  const canvas = tokenChartRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = rect.width * dpr
  canvas.height = rect.height * dpr
  ctx.scale(dpr, dpr)

  const w = rect.width
  const h = rect.height
  const pad = { top: 16, right: 16, bottom: 24, left: 40 }
  const pw = w - pad.left - pad.right
  const ph = h - pad.top - pad.bottom

  // 使用真实趋势数据或模拟数据
  const days = chartRange.value === '7d' ? 7 : 30
  const data = trendData.value.length >= days
    ? trendData.value.slice(-days)
    : Array.from({ length: days }, () => Math.floor(Math.random() * 6000 + 2000))

  const max = Math.max(...data)
  const gridLines = 4

  ctx.clearRect(0, 0, w, h)

  // 网格
  ctx.strokeStyle = 'rgba(255,255,255,0.05)'
  ctx.lineWidth = 1
  for (let i = 0; i <= gridLines; i++) {
    const y = pad.top + (ph / gridLines) * i
    ctx.beginPath()
    ctx.moveTo(pad.left, y)
    ctx.lineTo(w - pad.right, y)
    ctx.stroke()

    // 标签
    ctx.fillStyle = 'rgba(255,255,255,0.3)'
    ctx.font = '10px -apple-system, sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText(Math.round(max - (max / gridLines) * i).toLocaleString(), pad.left - 6, y + 3)
  }

  // 渐变折线
  const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + ph)
  gradient.addColorStop(0, 'rgba(96,165,250,0.3)')
  gradient.addColorStop(1, 'rgba(96,165,250,0)')

  ctx.beginPath()
  const xStep = pw / (data.length - 1)
  data.forEach((v, i) => {
    const x = pad.left + xStep * i
    const y = pad.top + ph - (v / max) * ph
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })

  // 面积
  ctx.lineTo(pad.left + xStep * (data.length - 1), pad.top + ph)
  ctx.lineTo(pad.left, pad.top + ph)
  ctx.closePath()
  ctx.fillStyle = gradient
  ctx.fill()

  // 线条
  ctx.beginPath()
  data.forEach((v, i) => {
    const x = pad.left + xStep * i
    const y = pad.top + ph - (v / max) * ph
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.strokeStyle = '#60a5fa'
  ctx.lineWidth = 2
  ctx.stroke()

  // 点
  data.forEach((v, i) => {
    const x = pad.left + xStep * i
    const y = pad.top + ph - (v / max) * ph
    ctx.beginPath()
    ctx.arc(x, y, 3, 0, Math.PI * 2)
    ctx.fillStyle = '#60a5fa'
    ctx.fill()
  })

  // X 轴标签
  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  ctx.font = '10px -apple-system, sans-serif'
  ctx.textAlign = 'center'
  const now = new Date()
  for (let i = 0; i < data.length; i += Math.ceil(data.length / 6)) {
    const d = new Date(now)
    d.setDate(d.getDate() - (data.length - 1 - i))
    const x = pad.left + xStep * i
    ctx.fillText(`${d.getMonth() + 1}/${d.getDate()}`, x, h - 4)
  }
}

onUnmounted(() => {
  window.removeEventListener('resize', drawChart)
  cancelAnimationFrame(chartAnimationId)
})
</script>

<style scoped>
.dashboard-page {
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ─── Welcome ─── */
.welcome-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 28px 32px;
  flex-wrap: wrap;
  gap: 16px;
}
.welcome-title {
  font-size: 1.6rem;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0 0 6px;
}
.welcome-wave {
  display: inline-block;
  animation: wave 0.8s ease-in-out infinite alternate;
}
@keyframes wave {
  0% { transform: rotate(-10deg); }
  100% { transform: rotate(15deg); }
}
.welcome-sub {
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.9rem;
  margin: 0;
}
.welcome-right {
  display: flex;
  gap: 12px;
}
.quick-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  border-radius: 8px;
  font-size: 0.9rem;
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  transition: all 0.2s;
}
.quick-badge:hover {
  background: rgba(96, 165, 250, 0.15);
  border-color: rgba(96, 165, 250, 0.3);
  color: #93c5fd;
}

/* ─── Stats ─── */
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 22px 24px;
}
.stat-card__icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.4rem;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 14%, transparent);
}
.stat-card__content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-card__label {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.45);
}
.stat-card__value {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--accent);
  line-height: 1.2;
}
.stat-card__trend {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.35);
  display: flex;
  align-items: center;
  gap: 2px;
}
.trend-up { color: #34d399; }
.trend-down { color: #fb7185; }

/* ─── Main content ─── */
.main-row {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 20px;
}
.main-left {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.main-right {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ─── Chart ─── */
.chart-card {
  padding: 20px 24px;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.chart-header h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0;
}
:deep(.chart-header .ant-radio-group) {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
}
:deep(.chart-header .ant-radio-button-wrapper) {
  background: transparent !important;
  border: none !important;
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.78rem;
  padding: 2px 12px;
  height: 28px;
  line-height: 28px;
}
:deep(.chart-header .ant-radio-button-wrapper-checked) {
  color: #60a5fa !important;
  background: rgba(96, 165, 250, 0.15) !important;
  border-radius: 4px;
}
.chart-container {
  width: 100%;
  height: 240px;
}
.token-chart {
  width: 100%;
  height: 100%;
}

/* ─── Quick Actions ─── */
.actions-card {
  padding: 20px 24px;
}
.actions-card h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 16px;
}
.action-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.action-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.25s;
  border: 1px solid transparent;
}
.action-item:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
  transform: translateY(-2px);
}
.action-item__icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
}
.action-item__label {
  font-size: 0.85rem;
  color: #e2e8f0;
  font-weight: 500;
}
.action-item__desc {
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.35);
}

/* ─── Recent ─── */
.recent-card,
.status-card {
  padding: 20px 24px;
}
.recent-card h3,
.status-card h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 16px;
}
.recent-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.recent-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.recent-item__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}
.recent-item__content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.recent-item__title {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.75);
}
.recent-item__time {
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.3);
}
.recent-empty {
  text-align: center;
  padding: 32px 0;
  color: rgba(255, 255, 255, 0.25);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.empty-icon {
  font-size: 2rem;
  opacity: 0.5;
}

/* ─── Status ─── */
.status-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.status-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.status-item__label {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
}

/* ─── Responsive ─── */
@media (max-width: 1200px) {
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .main-row { grid-template-columns: 1fr; }
  .action-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 768px) {
  .dashboard-page { padding: 16px; gap: 14px; }
  .stat-row { grid-template-columns: 1fr; }
  .action-grid { grid-template-columns: repeat(2, 1fr); }
  .welcome-section { flex-direction: column; align-items: flex-start; }
}
</style>
