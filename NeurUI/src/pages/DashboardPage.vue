<template>
  <div class="nr-dashboard">
    <!-- Welcome Section -->
    <div class="nr-dashboard-welcome">
      <div>
        <h1 class="nr-dashboard-greeting">
          {{ t('dashboard.welcome') }}, {{ authStore.currentUser?.username || t('auth.user') }}
        </h1>
        <p class="nr-dashboard-date">{{ currentDate }}</p>
      </div>
      <div class="nr-dashboard-status-badges">
        <a-badge :status="systemHealth.api ? 'success' : 'error'" :text="`${t('dashboard.api')}: ${systemHealth.api ? t('dashboard.ok') : t('dashboard.down')}`" />
        <a-badge :status="systemHealth.db ? 'success' : 'error'" :text="`${t('dashboard.db')}: ${systemHealth.db ? t('dashboard.ok') : t('dashboard.down')}`" />
        <a-badge :status="systemHealth.redis ? 'success' : 'error'" :text="`${t('dashboard.cache')}: ${systemHealth.redis ? t('dashboard.ok') : t('dashboard.down')}`" />
        <a-badge :status="systemHealth.queue ? 'success' : 'error'" :text="`${t('dashboard.queue')}: ${systemHealth.queue ? t('dashboard.ok') : t('dashboard.down')}`" />
      </div>
    </div>

    <!-- Stat Cards Grid -->
    <a-spin :spinning="dashboardLoading">
    <div class="nr-dashboard-stats">
      <GlassStatCard
        :label="t('dashboard.totalAgents')"
        :value="stats.totalAgents"
        :trend="stats.agentTrend"
        :spark-data="stats.agentSpark"
        spark-color="#6366f1"
        emoji="🤖"
      />
      <GlassStatCard
        :label="t('dashboard.totalConversations')"
        :value="stats.totalConversations"
        :trend="stats.conversationTrend"
        :spark-data="stats.conversationSpark"
        spark-color="#22d3ee"
        emoji="💬"
      />
      <GlassStatCard
        :label="t('dashboard.totalTokens')"
        :value="formatTokens(stats.totalTokens)"
        :trend="stats.tokenTrend"
        :spark-data="stats.tokenSpark"
        spark-color="#a78bfa"
        emoji="📊"
      />
      <GlassStatCard
        :label="t('dashboard.totalCalls')"
        :value="stats.totalCalls"
        :trend="stats.callTrend"
        :spark-data="stats.callSpark"
        spark-color="#10b981"
        emoji="⚡"
      />
    </div>
    </a-spin>

    <!-- Main Content Grid -->
    <div class="nr-dashboard-grid">
      <!-- Quick Actions -->
      <GlassCard :title="t('dashboard.quickActions')" variant="default" :radius="20">
        <div class="nr-quick-actions">
          <button class="nr-quick-action-btn" @click="$router.push('/agents/create')">
            <span class="nr-qa-icon" style="background: rgba(99,102,241,0.15); color: #818cf8;">+</span>
            <span class="nr-qa-label">{{ t('dashboard.createAgent') }}</span>
          </button>
          <button class="nr-quick-action-btn" @click="navigateToChat">
            <span class="nr-qa-icon" style="background: rgba(34,211,238,0.15); color: #22d3ee;">💬</span>
            <span class="nr-qa-label">{{ t('dashboard.startChat') }}</span>
          </button>
          <button class="nr-quick-action-btn" @click="$router.push('/marketplace/skills')">
            <span class="nr-qa-icon" style="background: rgba(167,139,250,0.15); color: #a78bfa;">🧩</span>
            <span class="nr-qa-label">{{ t('dashboard.manageSkills') }}</span>
          </button>
          <button class="nr-quick-action-btn" @click="$router.push('/analytics')">
            <span class="nr-qa-icon" style="background: rgba(16,185,129,0.15); color: #10b981;">📈</span>
            <span class="nr-qa-label">{{ t('dashboard.viewAnalytics') }}</span>
          </button>
        </div>
      </GlassCard>

      <!-- Token Usage Chart Area -->
      <GlassCard :title="t('dashboard.usage7d')" variant="default" :radius="20">
        <div class="nr-chart-placeholder" ref="chartRef">
          <div class="nr-chart-bars">
            <div
              v-for="(bar, i) in chartBars"
              :key="i"
              class="nr-chart-bar"
              :style="{ height: bar.height + '%', animationDelay: i * 0.08 + 's' }"
            >
              <span class="nr-chart-bar-label">{{ bar.label }}</span>
              <a-tooltip :title="bar.value + 'K tokens'">
                <div class="nr-chart-bar-fill" />
              </a-tooltip>
            </div>
          </div>
        </div>
      </GlassCard>

      <!-- Recent Activity -->
      <GlassCard :title="t('dashboard.recentActivity')" variant="default" :radius="20">
        <div class="nr-activity-list">
          <div v-if="activities.length === 0" class="nr-activity-empty">
            {{ t('common.noData') }}
          </div>
          <div
            v-for="(activity, i) in activities"
            :key="i"
            class="nr-activity-item"
          >
            <span class="nr-activity-icon" :style="{ background: activity.color }">
              {{ activity.icon }}
            </span>
            <div class="nr-activity-content">
              <span class="nr-activity-text">{{ activity.text }}</span>
              <span class="nr-activity-time">{{ activity.time }}</span>
            </div>
          </div>
        </div>
      </GlassCard>

      <!-- Feedback Quality（点赞/点踩 → 记忆温度闭环的可见性面板） -->
      <GlassCard :title="t('dashboard.feedbackCard')" variant="default" :radius="20">
        <div v-if="!feedbackSummary.hasFeedback" class="nr-feedback-empty">
          {{ t('dashboard.feedbackEmpty') }}
        </div>
        <template v-else>
          <div class="nr-feedback-summary">
            <div class="nr-feedback-rate">
              <span class="nr-feedback-rate-value">{{ satisfactionText }}</span>
              <span class="nr-feedback-rate-label">{{ t('dashboard.feedbackSatisfaction') }}</span>
            </div>
            <div class="nr-feedback-counts">
              <span class="nr-feedback-count nr-feedback-count--like">👍 {{ feedbackSummary.like }}</span>
              <span class="nr-feedback-count nr-feedback-count--dislike">👎 {{ feedbackSummary.dislike }}</span>
            </div>
          </div>
          <div class="nr-feedback-recent">
            <div
              v-for="(item, i) in feedbackSummary.recent.slice(0, 3)"
              :key="i"
              class="nr-feedback-item"
            >
              <span class="nr-feedback-item-icon">{{ item.feedback === 'like' ? '👍' : '👎' }}</span>
              <span class="nr-feedback-item-text">{{ item.content || '—' }}</span>
            </div>
          </div>
        </template>
      </GlassCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { getHomeData, getHomeTrends } from '@/api/modules/home'
import { statsApi } from '@/api/modules'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import { useFeedbackStats } from '@/composables/useFeedbackStats'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const agentStore = useAgentStore()

/** Current date formatted for display. */
const currentDate = computed(() => {
  const now = new Date()
  return now.toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
})

/** Dashboard statistics. */
const stats = reactive({
  totalAgents: 0,
  totalConversations: 0,
  totalTokens: 0,
  totalCalls: 0,
  agentTrend: 0,
  conversationTrend: 0,
  tokenTrend: 0,
  callTrend: 0,
  agentSpark: [] as number[],
  conversationSpark: [] as number[],
  tokenSpark: [] as number[],
  callSpark: [] as number[],
})

/** System health indicators. */
const systemHealth = reactive({
  api: true,
  db: true,
  redis: true,
  queue: true,
})

/** Recent activity entries. */
const activities = ref<Array<{
  icon: string
  text: string
  time: string
  color: string
}>>([])

/** Chart bar data for 7-day usage. */
const chartBars = ref<Array<{ label: string; height: number; value: number }>>([])

/** Loading state. */
const dashboardLoading = ref(false)

// ---------------------------------------------------------------------------
// 反馈质量卡片（点赞/点踩统计 → 满意度派生；失败保持零状态不拖垮仪表盘）
// ---------------------------------------------------------------------------
const {
  summary: feedbackSummary,
  satisfactionText,
  refresh: refreshFeedbackStats,
} = useFeedbackStats()

/** Format large token counts for display. */
function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

/** Navigate to chat with the first available agent. */
function navigateToChat() {
  if (agentStore.agents.length > 0) {
    const firstActive = agentStore.agents.find((a) => a.status === 'active') || agentStore.agents[0]
    router.push(`/agent/${firstActive.id}/chat`)
  } else {
    router.push('/agents/create')
  }
}

/** Fetch dashboard data from the API. */
async function fetchDashboardData() {
  try {
    const [homeRes, trendsRes] = await Promise.allSettled([
      getHomeData(),
      getHomeTrends(7),
    ])

    // --- Home data ---
    if (homeRes.status === 'fulfilled') {
      const raw: any = homeRes.value
      const data = raw?.data ?? raw
      if (data) {
        const s = data.stats ?? {}
        const t = data.trends ?? {}

        stats.totalAgents = s.agent_count ?? agentStore.agents.length
        stats.totalConversations = s.conversation_count ?? 0
        stats.totalTokens = s.token_consumption ?? 0
        stats.totalCalls = s.llm_call_count ?? 0

        stats.agentTrend = t.agent_trend ?? 0
        stats.conversationTrend = t.conversation_trend ?? 0
        stats.tokenTrend = t.token_trend ?? 0
        stats.callTrend = t.plugin_trend ?? 0

        if (data.recent_activities && Array.isArray(data.recent_activities)) {
          activities.value = data.recent_activities.slice(0, 5).map((a: any) => ({
            icon: a.icon || '📌',
            text: a.text || a.message || a.title || 'Activity',
            time: formatTimeAgo(a.created_at || a.timestamp),
            color: a.color || 'rgba(99,102,241,0.15)',
          }))
        }
      }
    }

    // --- Trends (sparklines + chart) ---
    if (trendsRes.status === 'fulfilled') {
      const raw: any = trendsRes.value
      const data = raw?.data ?? raw
      if (data) {
        const agentT = data.agent_trend?.data
        const convT = data.conversation_trend?.data
        const tokenT = data.token_trend?.data
        const llmT = data.llm_trend?.data
        const labels = data.agent_trend?.labels ?? []

        if (agentT) stats.agentSpark = agentT
        if (convT) stats.conversationSpark = convT
        if (tokenT) stats.tokenSpark = tokenT
        if (llmT) stats.callSpark = llmT

        if (tokenT && labels.length) {
          buildChartBars(labels.map((l: string, i: number) => ({ day: l, value: tokenT[i] ?? 0 })))
        }
      }
    }
  } catch {
    // API unreachable — show zeros instead of demo data
    stats.totalAgents = agentStore.agents.length
  }
}

/** Fetch system health status. */
async function fetchSystemHealth() {
  try {
    const data = await statsApi.getSystemInfo()

    if (data) {
      // Backend returns { status, cpu, memory, disk } — all present means healthy
      systemHealth.api = data.status === 'running'
      systemHealth.db = true // DB check is internal; assume healthy if API responds
      systemHealth.redis = (data.memory?.percent ?? 0) < 90
      systemHealth.queue = true
    }
  } catch {
    systemHealth.api = false
  }
}

/** Build chart bars from usage data. */
function buildChartBars(usageData: Array<{ day?: string; label?: string; value: number }>) {
  const maxVal = Math.max(...usageData.map((d) => d.value), 1)
  chartBars.value = usageData.map((d) => ({
    label: d.day || d.label || '',
    height: Math.max(8, (d.value / maxVal) * 100),
    value: Math.round(d.value),
  }))
}

/** Format a timestamp to relative time string. */
function formatTimeAgo(timestamp: string | number): string {
  const date = new Date(timestamp)
  const now = Date.now()
  const diffMs = now - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)

  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString()
}

onMounted(async () => {
  dashboardLoading.value = true
  // Load agents in parallel with dashboard data
  await Promise.allSettled([
    agentStore.loadAgents(),
    fetchDashboardData(),
    fetchSystemHealth(),
    refreshFeedbackStats(),
  ])
  dashboardLoading.value = false
})
</script>

<style scoped>
.nr-dashboard {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 4px;
  animation: dash-enter 0.5s ease both;
}

@keyframes dash-enter {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Welcome Section */
.nr-dashboard-welcome {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.nr-dashboard-greeting {
  font-family: var(--nr-font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--nr-text-primary);
  letter-spacing: -0.03em;
  margin: 0;
}

.nr-dashboard-date {
  font-size: 14px;
  color: var(--nr-text-tertiary);
  margin: 4px 0 0;
}

.nr-dashboard-status-badges {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

:deep(.ant-badge-status-text) {
  color: var(--nr-text-secondary) !important;
  font-size: 12px;
}

/* Stats Grid */
.nr-dashboard-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

@media (max-width: 1200px) {
  .nr-dashboard-stats { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 600px) {
  .nr-dashboard-stats { grid-template-columns: 1fr; }
}

/* Content Grid */
.nr-dashboard-grid {
  display: grid;
  grid-template-columns: 1fr 1.5fr 1fr;
  gap: 16px;
}

@media (max-width: 1200px) {
  .nr-dashboard-grid { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 768px) {
  .nr-dashboard-grid { grid-template-columns: 1fr; }
}

/* Quick Actions */
.nr-quick-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px;
}

.nr-quick-action-btn {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 12px 16px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 12px;
  background: var(--nr-glass-bg);
  cursor: pointer;
  transition: all 0.25s ease;
  color: var(--nr-text-primary);
}

.nr-quick-action-btn:hover {
  background: var(--nr-glass-bg-hover);
  border-color: var(--nr-glass-border-hover);
}

.nr-qa-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.nr-qa-label {
  font-size: 14px;
  font-weight: 500;
}

/* Chart Placeholder */
.nr-chart-placeholder {
  height: 200px;
  padding: 8px 4px;
}

.nr-chart-bars {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 100%;
  gap: 8px;
}

.nr-chart-bar {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  gap: 6px;
}

.nr-chart-bar-fill {
  width: 100%;
  height: 100%;
  border-radius: 6px 6px 2px 2px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--nr-primary) 60%, transparent) 0%, color-mix(in srgb, var(--nr-primary) 20%, transparent) 100%);
  transition: background 0.3s;
  animation: bar-grow 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.nr-chart-bar:hover .nr-chart-bar-fill {
  background: linear-gradient(180deg, color-mix(in srgb, var(--nr-primary) 80%, transparent) 0%, color-mix(in srgb, var(--nr-primary) 35%, transparent) 100%);
}

@keyframes bar-grow {
  from { transform: scaleY(0); transform-origin: bottom; }
  to { transform: scaleY(1); transform-origin: bottom; }
}

.nr-chart-bar-label {
  font-size: 10px;
  color: var(--nr-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* Activity List */
.nr-activity-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nr-activity-empty {
  text-align: center;
  color: var(--nr-text-muted);
  padding: 32px 0;
  font-size: 13px;
}

.nr-activity-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 8px;
  border-radius: 10px;
  transition: background 0.2s;
}

.nr-activity-item:hover {
  background: var(--nr-glass-bg);
}

.nr-activity-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.nr-activity-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.nr-activity-text {
  font-size: 13px;
  color: var(--nr-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nr-activity-time {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}

/* ── Feedback Quality card ─────────────────────────────── */

.nr-feedback-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 96px;
  color: var(--nr-text-muted);
  font-size: 13px;
}

.nr-feedback-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.nr-feedback-rate {
  display: flex;
  flex-direction: column;
}

.nr-feedback-rate-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--nr-primary);
  line-height: 1.1;
  font-family: var(--nr-font-mono);
}

.nr-feedback-rate-label {
  font-size: 12px;
  color: var(--nr-text-muted);
}

.nr-feedback-counts {
  display: flex;
  gap: 8px;
}

.nr-feedback-count {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
}

.nr-feedback-count--like {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.nr-feedback-count--dislike {
  background: rgba(229, 72, 77, 0.12);
  color: #e5484d;
}

.nr-feedback-recent {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nr-feedback-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 10px;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
}

.nr-feedback-item-icon {
  flex-shrink: 0;
  font-size: 12px;
}

.nr-feedback-item-text {
  font-size: 12px;
  color: var(--nr-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
