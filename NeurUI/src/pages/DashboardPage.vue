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
      <div class="nr-dashboard-toolbar">
        <a-badge
          v-if="health.overall"
          :status="healthStatus"
          :text="t('dashboard.statusHealthy')"
        />
        <GlassButton size="sm" variant="ghost" @click="refreshAll">
          🔄 {{ t('dashboard.refresh') }}
        </GlassButton>
      </div>
    </div>

    <!-- Core Import Failure Bar -->
    <div v-if="error" class="nr-dashboard-error">
      <span>⚠️ {{ t('dashboard.loadError') }}</span>
      <GlassButton size="sm" variant="ghost" @click="refreshAll">
        {{ t('dashboard.retry') }}
      </GlassButton>
    </div>

    <!-- Stat Cards Grid（6 张真实 KPI 卡） -->
    <a-spin :spinning="loading">
      <div class="nr-dashboard-stats">
        <GlassStatCard
          v-for="card in cards"
          :key="card.key"
          :label="t(CARD_META[card.key].labelKey)"
          :value="formatCardValue(card)"
          :emoji="CARD_META[card.key].emoji"
          :spark-color="CARD_META[card.key].color"
          :trend="card.trend"
          :spark-data="card.spark"
          :class="{ 'nr-stat-card--link': card.key === 'tokens' }"
          :title="card.key === 'tokens' ? t('dashboard.usageStatsEntry') : undefined"
          @click="card.key === 'tokens' && router.push('/usage-stats')"
        />
      </div>
    </a-spin>

    <!-- Main Content Grid -->
    <div class="nr-dashboard-grid">
      <!-- 7 天活跃趋势（echarts，会话/消息真实聚合） -->
      <GlassCard :title="t('dashboard.trends7d')" variant="default" :radius="20">
        <div class="nr-chart-wrap">
          <VChart v-if="trendChartOption" :option="trendChartOption" autoresize />
          <a-empty v-else :description="t('dashboard.noTrendData')" />
        </div>
      </GlassCard>

      <!-- 模型 Token 分布（echarts 环形，服务启动后真实累计） -->
      <GlassCard :title="t('dashboard.tokenDistribution')" variant="default" :radius="20">
        <div class="nr-chart-wrap">
          <VChart v-if="tokenPieOption" :option="tokenPieOption" autoresize />
          <a-empty v-else :description="t('dashboard.noTokenData')" />
        </div>
      </GlassCard>

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

      <!-- System Health（真实: health checks + 调度器 + 系统资源） -->
      <GlassCard :title="t('dashboard.systemHealth')" variant="default" :radius="20" class="nr-health-card">
        <div class="nr-health-resources">
          <div class="nr-health-res-item">
            <a-progress
              type="circle"
              :percent="health.system?.cpu ?? 0"
              :size="76"
              :status="(health.system?.cpu ?? 0) > 80 ? 'exception' : 'normal'"
            />
            <span class="nr-health-res-label">{{ t('dashboard.healthCpu') }}</span>
          </div>
          <div class="nr-health-res-item">
            <a-progress
              type="circle"
              :percent="health.system?.memory ?? 0"
              :size="76"
              :status="(health.system?.memory ?? 0) > 85 ? 'exception' : 'normal'"
            />
            <span class="nr-health-res-label">{{ t('dashboard.healthMemory') }}</span>
          </div>
          <div class="nr-health-res-item">
            <a-progress
              type="circle"
              :percent="health.system?.disk ?? 0"
              :size="76"
              :status="(health.system?.disk ?? 0) > 90 ? 'exception' : 'normal'"
            />
            <span class="nr-health-res-label">{{ t('dashboard.healthDisk') }}</span>
          </div>
        </div>
        <div class="nr-health-meta">
          <a-tag :color="scheduler.running ? 'green' : 'orange'">
            {{ scheduler.running ? t('dashboard.schedulerRunning') : t('dashboard.schedulerIdle') }}
          </a-tag>
          <span class="nr-health-meta-text">
            {{ t('dashboard.schedulerTasks', { total: scheduler.total_tasks ?? 0 }) }}
          </span>
        </div>
        <div class="nr-health-checks">
          <div v-for="check in health.checks" :key="check.name" class="nr-health-check">
            <a-badge
              :status="check.status === 'pass' ? 'success' : (check.status === 'warn' ? 'warning' : 'error')"
            />
            <span class="nr-health-check-name">{{ check.name }}</span>
          </div>
          <div v-if="health.checks.length === 0" class="nr-health-check--none">
            {{ t('common.noData') }}
          </div>
        </div>
      </GlassCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassCard from '@/components/GlassCard.vue'
import { useDashboardStats, type DashboardStatCard } from '@/composables/useDashboardStats'
import { useFeedbackStats } from '@/composables/useFeedbackStats'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const agentStore = useAgentStore()

const currentDate = new Date().toLocaleDateString()

const {
  cards,
  trends,
  tokenByModel,
  health,
  scheduler,
  loading,
  error,
  refresh: refreshStats,
} = useDashboardStats({
  agentId: () => agentStore.agents[0]?.id ?? '',
})

const {
  summary: feedbackSummary,
  satisfactionText,
  refresh: refreshFeedbackStats,
} = useFeedbackStats()

/** 统计卡展示元数据（emoji/色彩/label i18n 键/数值格式化） */
const CARD_META: Record<
  DashboardStatCard['key'],
  { emoji: string; color: string; labelKey: string; format?: (n: number) => string }
> = {
  agents: { emoji: '🤖', color: '#6366f1', labelKey: 'dashboard.totalAgents' },
  conversations: { emoji: '💬', color: '#22d3ee', labelKey: 'dashboard.totalConversations' },
  tokens: { emoji: '📊', color: '#a78bfa', labelKey: 'dashboard.totalTokens', format: formatTokens },
  calls: { emoji: '⚡', color: '#10b981', labelKey: 'dashboard.totalCalls' },
  memories: { emoji: '🧠', color: '#f472b6', labelKey: 'dashboard.totalMemories' },
  knowledge: { emoji: '📚', color: '#fbbf24', labelKey: 'dashboard.totalKnowledge' },
}

const healthStatus = computed(() => {
  const o = health.value.overall
  return o === 'healthy' ? 'success' : o === 'degraded' ? 'warning' : 'error'
})

/** 7 天活跃趋势：会话柱状 + 消息折线（双轴） */
const trendChartOption = computed(() => {
  const tr = trends.value
  if (!tr.labels.length) return null
  return {
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8' } },
    grid: { left: 44, right: 48, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: tr.labels },
    yAxis: [
      { type: 'value', name: t('dashboard.trendSession'), nameTextStyle: { color: '#94a3b8' } },
      { type: 'value', name: t('dashboard.trendMessage'), nameTextStyle: { color: '#94a3b8' } },
    ],
    series: [
      { name: t('dashboard.trendSession'), type: 'bar', data: tr.conversation, barWidth: '44%', itemStyle: { color: '#22d3ee' } },
      { name: t('dashboard.trendMessage'), type: 'line', yAxisIndex: 1, smooth: true, data: tr.message, itemStyle: { color: '#a78bfa' } },
    ],
  }
})

/** 模型 Token 分布（进程内真实记账，无记录时空态） */
const tokenPieOption = computed(() => {
  if (!tokenByModel.value.length) return null
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: '#94a3b8' } },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '44%'],
        data: tokenByModel.value.map((m) => ({ name: m.model, value: m.total_tokens })),
        label: { color: '#94a3b8', fontSize: 11 },
      },
    ],
  }
})

/** Format large token counts for display. */
function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

/** 取卡片数值（有格式化函数则应用，无则原样）。模板内二次索引会丢失 TS 收窄，故收敛到函数。 */
function formatCardValue(card: DashboardStatCard): number | string {
  const f = CARD_META[card.key].format
  return f ? f(card.value) : card.value
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

async function refreshAll() {
  await Promise.allSettled([refreshStats(), refreshFeedbackStats()])
}

onMounted(() => {
  void Promise.allSettled([agentStore.loadAgents(), refreshAll()])
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

.nr-dashboard-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

:deep(.ant-badge-status-text) {
  color: var(--nr-text-secondary) !important;
  font-size: 12px;
}

/* Import failure bar */
.nr-dashboard-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  border-radius: 12px;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.35);
  color: #ef4444;
  font-size: 13px;
  font-weight: 500;
}

/* Stats Grid */
.nr-dashboard-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

/* Token 卡 = 使用统计入口（点击跳转 /usage-stats） */
.nr-stat-card--link {
  cursor: pointer;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.nr-stat-card--link:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(167, 139, 250, 0.18);
  border-color: var(--nr-glass-border-hover, rgba(167, 139, 250, 0.4));
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
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 1200px) {
  .nr-dashboard-grid { grid-template-columns: 1fr; }
}

/* Charts */
.nr-chart-wrap {
  height: 260px;
}

.nr-chart-wrap .vchart-stub {
  width: 100%;
  height: 100%;
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

/* ── System Health card ────────────────────────────────── */

.nr-health-resources {
  display: flex;
  gap: 24px;
  justify-content: space-around;
  margin-bottom: 14px;
}

.nr-health-res-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.nr-health-res-label {
  font-size: 12px;
  color: var(--nr-text-tertiary);
}

.nr-health-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.nr-health-meta-text {
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.nr-health-checks {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nr-health-check {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 10px;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
}

.nr-health-check-name {
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.nr-health-check--none {
  font-size: 12px;
  color: var(--nr-text-muted);
  text-align: center;
  padding: 12px 0;
}
</style>
