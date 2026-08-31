<template>
  <div class="stats-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('stats.title') }}</h2>
        <p class="page-global-hint">{{ t('common.globalSettingHint') }}</p>
      </div>
      <div class="header-actions">
        <a-radio-group v-model:value="timeRange" button-style="solid" size="small" @change="fetchAll">
          <a-radio-button value="day">{{ t('analytics.day') }}</a-radio-button>
          <a-radio-button value="week">{{ t('analytics.week') }}</a-radio-button>
          <a-radio-button value="month">{{ t('analytics.month') }}</a-radio-button>
        </a-radio-group>
        <GlassButton variant="secondary" size="sm" :loading="exporting" @click="doExportStats">{{ t('common.export') }}</GlassButton>
      </div>
    </div>

    <template v-if="!isAdmin">
      <div class="admin-gate">{{ t('common.adminOnlyHint') }}</div>
    </template>
    <template v-else>
    <a-tabs v-model:activeKey="activeTab" @change="fetchAll">
      <!-- Overview tab -->
      <a-tab-pane key="overview" :tab="t('system.overview')">
        <a-spin :spinning="loading">
          <div class="stats-grid">
            <GlassStatCard :label="t('dashboard.totalAgents')" :value="overview.agents ?? 0" emoji="🤖" :trend="overview.agents_trend" />
            <GlassStatCard :label="t('dashboard.totalConversations')" :value="overview.conversations ?? 0" emoji="💬" :trend="overview.conversations_trend" />
            <GlassStatCard :label="t('dashboard.totalTokens')" :value="overview.tokens ?? 0" emoji="🔤" :trend="overview.tokens_trend" />
            <GlassStatCard :label="t('dashboard.totalCalls')" :value="overview.api_calls ?? 0" emoji="📡" :trend="overview.api_calls_trend" />
            <GlassStatCard :label="t('system.errors')" :value="overview.errors ?? 0" emoji="❌" :trend="overview.errors_trend" />
          </div>
        </a-spin>

        <!-- Per-agent stats table -->
        <GlassCard :title="t('agent.stats')" style="margin-top: 20px">
          <a-table
            :columns="agentColumns"
            :data-source="agentStats"
            :loading="loading"
            row-key="id"
            :pagination="{ pageSize: 15 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <span class="agent-name">{{ record.name }}</span>
              </template>
              <template v-if="column.key === 'tokens'">
                <span class="mono">{{ record.tokens?.toLocaleString() ?? 0 }}</span>
              </template>
              <template v-if="column.key === 'status'">
                <a-badge :status="record.status === 'active' ? 'success' : 'default'" :text="record.status" />
              </template>
            </template>
          </a-table>
        </GlassCard>

        <!-- Usage trends -->
        <GlassCard :title="t('stats.usageTrends')" style="margin-top: 20px">
          <div class="chart-area">
            <div v-for="(point, i) in trends" :key="i" class="chart-bar-wrapper">
              <div class="chart-bar" :style="{ height: `${Math.max(4, (point.value / (maxTrend || 1)) * 140)}px` }" />
              <span class="chart-label">{{ point.label }}</span>
            </div>
            <a-empty v-if="!trends.length" :description="t('common.noData')" />
          </div>
        </GlassCard>
      </a-tab-pane>

      <!-- Performance tab -->
      <a-tab-pane key="performance" :tab="t('system.performance')">
        <a-spin :spinning="loading">
          <div class="stats-grid">
            <GlassStatCard :label="t('analytics.avgResponse')" :value="`${perfData.avg_response_ms ?? 0}ms`" emoji="⚡" />
            <GlassStatCard :label="t('analytics.p95Latency')" :value="`${perfData.p95_ms ?? 0}ms`" emoji="📊" />
            <GlassStatCard :label="t('analytics.throughput')" :value="`${perfData.throughput ?? 0}/s`" emoji="🚀" />
            <GlassStatCard :label="t('analytics.errorRate')" :value="`${perfData.error_rate ?? 0}%`" emoji="⚠️" />
          </div>
          <GlassCard :title="t('analytics.responseTimes')" style="margin-top: 20px">
            <a-table :columns="perfColumns" :data-source="perfData.endpoints ?? []" row-key="path" :pagination="false" size="small" />
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Behavior tab -->
      <a-tab-pane key="behavior" :tab="t('analytics.behavior')">
        <a-spin :spinning="loading">
          <div class="two-col">
            <GlassCard :title="t('analytics.popularFeatures')">
              <a-list :data-source="behaviorData.popular_features ?? []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <div class="feature-item">
                      <span>{{ item.name }}</span>
                      <a-tag>{{ item.count }}</a-tag>
                    </div>
                  </a-list-item>
                </template>
                <template #empty><a-empty :description="t('common.noData')" /></template>
              </a-list>
            </GlassCard>
            <GlassCard :title="t('analytics.userPaths')">
              <a-list :data-source="behaviorData.user_paths ?? []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <span class="path-item">{{ item.path }} ({{ item.count }})</span>
                  </a-list-item>
                </template>
                <template #empty><a-empty :description="t('common.noData')" /></template>
              </a-list>
            </GlassCard>
          </div>
        </a-spin>
      </a-tab-pane>

      <!-- Errors tab -->
      <a-tab-pane key="errors" :tab="t('system.errors')">
        <a-spin :spinning="loading">
          <div class="stats-grid">
            <GlassStatCard :label="t('analytics.totalErrors')" :value="errorData.total ?? 0" emoji="❌" :trend="errorData.trend" />
            <GlassStatCard :label="t('analytics.errorRate')" :value="`${errorData.rate ?? 0}%`" emoji="📉" />
          </div>
          <GlassCard :title="t('analytics.topErrors')" style="margin-top: 20px">
            <a-table :columns="errorColumns" :data-source="errorData.top_errors ?? []" row-key="code" :pagination="false" size="small" />
          </GlassCard>
        </a-spin>
      </a-tab-pane>
    </a-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { statsApi } from '@/api/modules'
import * as analyticsApi from '@/api/modules/analytics'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
/** 系统统计为全局数据; 仅管理员可访问 */
const isAdmin = computed(() => authStore.user?.role === 'admin')

const activeTab = ref('overview')
const timeRange = ref('week')
const loading = ref(false)
const exporting = ref(false)

const overview = ref<Record<string, any>>({})
const agentStats = ref<statsApi.AgentStats[]>([])
const trends = ref<statsApi.TrendPoint[]>([])
const perfData = ref<Record<string, any>>({})
const behaviorData = ref<Record<string, any>>({})
const errorData = ref<Record<string, any>>({})

const maxTrend = computed(() => Math.max(...trends.value.map((p) => p.value || 0), 1))

const agentColumns = computed(() => [
  { title: t('common.name'), key: 'name', dataIndex: 'name' },
  { title: t('common.status'), key: 'status' },
  { title: t('dashboard.totalConversations'), dataIndex: 'conversations', key: 'conversations' },
  { title: t('dashboard.totalTokens'), key: 'tokens' },
  { title: t('dashboard.totalCalls'), dataIndex: 'api_calls', key: 'api_calls' },
  { title: t('system.errors'), dataIndex: 'errors', key: 'errors' },
])

const perfColumns = computed(() => [
  { title: t('analytics.endpoint'), dataIndex: 'path', key: 'path' },
  { title: t('analytics.avgMs'), dataIndex: 'avg_ms', key: 'avg_ms' },
  { title: t('analytics.p95Ms'), dataIndex: 'p95_ms', key: 'p95_ms' },
  { title: t('analytics.calls'), dataIndex: 'count', key: 'count' },
])

const errorColumns = computed(() => [
  { title: t('analytics.errorCode'), dataIndex: 'code', key: 'code' },
  { title: t('analytics.message'), dataIndex: 'message', key: 'message' },
  { title: t('analytics.count'), dataIndex: 'count', key: 'count' },
])

const fetchAll = async () => {
  loading.value = true
  try {
    await Promise.all([fetchOverview(), fetchAnalytics()])
  } finally {
    loading.value = false
  }
}

const fetchOverview = async () => {
  try {
    const [overviewRes, agentsRes] = await Promise.all([
      statsApi.getSystemStats(),
      statsApi.getAgentStats(),
    ])
    const ov = overviewRes ?? {}
    overview.value = ov.overview ?? ov
    trends.value = ov.trends ?? ov.timeline ?? []
    agentStats.value = Array.isArray(agentsRes) ? agentsRes : []
  } catch {
    // silent
  }
}

const fetchAnalytics = async () => {
  try {
    const range = timeRange.value
    const [perfRes, behaviorRes, errorRes] = await Promise.all([
      analyticsApi.getPerformanceAnalytics({ period: range }),
      analyticsApi.getBehaviorAnalytics({ period: range }),
      analyticsApi.getErrorAnalytics({ period: range }),
    ])
    perfData.value = (perfRes?.data ?? {}) as Record<string, any>
    behaviorData.value = (behaviorRes?.data ?? {}) as Record<string, any>
    errorData.value = (errorRes?.data ?? {}) as Record<string, any>
  } catch {
    // silent
  }
}

const doExportStats = async () => {
  exporting.value = true
  try {
    const res = await statsApi.exportStats()
    const blob = new Blob([res], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'stats-export.json'
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    exporting.value = false
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.stats-page { display: flex; flex-direction: column; gap: 20px; }
/* 全局说明与权限提示 */
.page-global-hint { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-secondary, #8a8a92); }
.admin-gate { margin: 24px auto; max-width: 480px; padding: 16px; border: 1px dashed var(--nr-border, rgba(255, 255, 255, 0.12)); border-radius: 10px; text-align: center; font-size: 13px; color: var(--nr-text-secondary, #8a8a92); }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 12px; align-items: center; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.agent-name { font-weight: 500; color: var(--nr-text-primary); }
.mono { font-family: var(--nr-font-mono); font-size: 13px; }
.chart-area { display: flex; align-items: flex-end; gap: 6px; min-height: 160px; padding: 12px 0; }
.chart-bar-wrapper { display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1; }
.chart-bar { width: 100%; max-width: 36px; background: linear-gradient(180deg, #6366f1, #8b5cf6); border-radius: 4px 4px 0 0; transition: height 0.3s; }
.chart-label { font-size: 10px; color: var(--nr-text-muted); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.feature-item { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.path-item { font-family: var(--nr-font-mono); font-size: 13px; }
</style>
