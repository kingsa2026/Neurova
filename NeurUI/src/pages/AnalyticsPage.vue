<template>
  <div class="analytics-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.analytics') }}</h2>
      <a-radio-group v-model:value="timeRange" button-style="solid" size="small" @change="fetchAll">
        <a-radio-button value="day">{{ t('analytics.day') }}</a-radio-button>
        <a-radio-button value="week">{{ t('analytics.week') }}</a-radio-button>
        <a-radio-button value="month">{{ t('analytics.month') }}</a-radio-button>
      </a-radio-group>
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="fetchAll">
      <!-- Overview tab（原 /stats 页的系统级统计；admin 门禁内嵌于 section） -->
      <a-tab-pane key="overview" :tab="t('system.overview')">
        <KeepAlive>
          <SystemOverviewSection v-if="activeTab === 'overview'" />
        </KeepAlive>
      </a-tab-pane>

      <!-- Usage tab -->
      <a-tab-pane key="usage" :tab="t('system.usage')">
        <a-spin :spinning="loading">
          <div class="stats-grid">
            <GlassStatCard :label="t('dashboard.totalConversations')" :value="usageData.conversations ?? 0" emoji="💬" :trend="usageData.conversations_trend" />
            <GlassStatCard :label="t('dashboard.totalTokens')" :value="usageData.tokens ?? 0" emoji="🔤" :trend="usageData.tokens_trend" />
            <GlassStatCard :label="t('dashboard.totalCalls')" :value="usageData.api_calls ?? 0" emoji="📡" :trend="usageData.api_calls_trend" />
            <GlassStatCard :label="t('dashboard.totalAgents')" :value="usageData.agents ?? 0" emoji="🤖" :trend="usageData.agents_trend" />
            <!-- B1-5：Prompt Cache 命中率（真实口径，无 cache 明细为 0） -->
            <GlassStatCard :label="t('analytics.cacheHitRate')" :value="`${((usageData.cache_hit_rate ?? 0) * 100).toFixed(1)}%`" emoji="🎯" />
          </div>
          <GlassCard :title="t('analytics.usageOverTime')" style="margin-top: 20px">
            <div class="chart-placeholder">
              <div v-for="(point, i) in usageData.timeline ?? []" :key="i" class="chart-bar-wrapper">
                <div class="chart-bar" :style="{ height: `${Math.max(4, (point.value / (usageData.max_value || 1)) * 160)}px` }" />
                <span class="chart-label">{{ point.label }}</span>
              </div>
              <a-empty v-if="!(usageData.timeline?.length)" :description="t('common.noData')" />
            </div>
          </GlassCard>
          <!-- B3-2：按 agent token 用量（usage_history agent_id 真值聚合） -->
          <GlassCard :title="t('analytics.byAgent')" style="margin-top: 20px">
            <a-table
              :columns="agentUsageColumns"
              :data-source="agentUsage"
              row-key="agent_id"
              :pagination="false"
              size="small"
            />
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Token activity tab（原 /usage-stats 页整体迁入；KeepAlive 保持状态、按 Tab 惰性挂载取数） -->
      <a-tab-pane key="tokens" :tab="t('usageStats.title')">
        <KeepAlive>
          <TokenActivitySection v-if="activeTab === 'tokens'" />
        </KeepAlive>
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
  </div>
</template>

<script setup lang="ts">
// 六页整合的统一分析入口（工单集 §46）：本容器承载六 Tab——
// 概览(原 /stats，admin)/用量/Token 活动(原 /usage-stats)/性能/行为/错误。
// 性能/行为/错误此前与 /stats 逐行重复，现只保留这一份实现。
// ?tab= 深链：/stats → ?tab=overview、/usage-stats → ?tab=tokens 的重定向落地页。
import { ref, onMounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import { message } from 'ant-design-vue'
import * as analyticsApi from '@/api/modules/analytics'
import SystemOverviewSection from './analytics/SystemOverviewSection.vue'
import TokenActivitySection from './analytics/TokenActivitySection.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const TAB_KEYS = ['overview', 'usage', 'tokens', 'performance', 'behavior', 'errors'] as const
type TabKey = (typeof TAB_KEYS)[number]

function tabFromQuery(v: unknown): TabKey {
  return typeof v === 'string' && (TAB_KEYS as readonly string[]).includes(v) ? (v as TabKey) : 'usage'
}

const activeTab = ref<TabKey>(tabFromQuery(route.query.tab))
const timeRange = ref('week')
const loading = ref(false)

// ?tab= 深链双向同步：query 变化（重定向/手改 URL）驱动 Tab；切 Tab 写回 query
// （replace 不产生历史噪音；同值短路防循环）。
watch(() => route.query.tab, (v) => {
  const next = tabFromQuery(v)
  if (next !== activeTab.value) activeTab.value = next
})
watch(activeTab, (v) => {
  if (route.query.tab !== v) {
    router.replace({ query: { ...route.query, tab: v } })
  }
})

const usageData = ref<Record<string, any>>({})
// B3-2：按 agent 用量（/analytics/usage by_agent 携带 tokens/calls）
const agentUsage = ref<{ agent_id: string; name?: string; requests: number; tokens?: number; calls?: number }[]>([])
const agentUsageColumns = computed(() => [
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id' },
  { title: t('analytics.sessions'), dataIndex: 'requests', key: 'requests' },
  { title: t('analytics.tokensCol'), dataIndex: 'tokens', key: 'tokens' },
  { title: t('analytics.llmCalls'), dataIndex: 'calls', key: 'calls' },
])
const perfData = ref<Record<string, any>>({})
const behaviorData = ref<Record<string, any>>({})
const errorData = ref<Record<string, any>>({})

const perfColumns = computed(() => [
  { title: t('analytics.endpoint'), dataIndex: 'path', key: 'path' },
  { title: t('analytics.avgMs'), dataIndex: 'avg_ms', key: 'avg_ms' },
  { title: t('analytics.p95Ms'), dataIndex: 'p95_ms', key: 'p95_ms' },
  { title: t('analytics.calls'), dataIndex: 'count', key: 'count' },
])

const errorColumns = computed(() => [
  { title: t('analytics.code'), dataIndex: 'code', key: 'code' },
  { title: t('analytics.errorMessage'), dataIndex: 'message', key: 'message', ellipsis: true },
  { title: t('analytics.count'), dataIndex: 'count', key: 'count' },
])

const fetchAll = async () => {
  // overview/tokens 两个 Tab 的数据由各自的 section 自取（挂载即拉、KeepAlive 保状态），
  // 容器的 fetchAll 只管自己拥有的四个 Tab——a-tabs @change 对这两 Tab 是无害空转。
  if (!(TAB_KEYS as readonly string[]).includes(activeTab.value)
    || activeTab.value === 'overview' || activeTab.value === 'tokens') return
  loading.value = true
  try {
    const params = { period: timeRange.value }
    if (activeTab.value === 'usage') {
      const res = await analyticsApi.getUsageAnalytics(params)
      const d = res?.data ?? res ?? {} as any
      const byAgents = d.by_agent ?? []
      agentUsage.value = byAgents
      usageData.value = {
        cache_hit_rate: d.cache_hit_rate ?? 0,
        cache_read_tokens: d.cache_read_tokens ?? 0,
        conversations: byAgents.reduce((sum: number, a: any) => sum + (a.requests ?? 0), 0),
        tokens: d.total_tokens ?? 0,
        api_calls: d.total_requests ?? 0,
        agents: byAgents.length,
        timeline: (d.daily_trend ?? []).map((p: any) => ({ label: p.date, value: p.requests })),
        max_value: Math.max(...(d.daily_trend ?? []).map((p: any) => p.requests), 1),
      }
    } else if (activeTab.value === 'performance') {
      const res = await analyticsApi.getPerformanceAnalytics(params)
      const d = res?.data ?? res ?? {} as any
      perfData.value = {
        avg_response_ms: Math.round(d.avg_latency_ms ?? 0),
        p95_ms: Math.round(d.p95_latency_ms ?? 0),
        throughput: d.throughput_rps ?? 0,
        error_rate: d.error_rate ?? 0,
        endpoints: (d.by_endpoint ?? []).map((e: any) => ({ path: e.endpoint, avg_ms: e.avg_ms, count: e.count })),
      }
    } else if (activeTab.value === 'behavior') {
      const res = await analyticsApi.getBehaviorAnalytics(params)
      const d = res?.data ?? res ?? {} as any
      behaviorData.value = {
        popular_features: (d.top_tools ?? []).map((t: any) => ({ name: t.name, count: t.usage_count })),
        user_paths: (d.conversation_patterns ?? []).map((p: any) => ({ path: p.pattern, count: p.count })),
      }
    } else if (activeTab.value === 'errors') {
      const res = await analyticsApi.getErrorAnalytics(params)
      const d = res?.data ?? res ?? {} as any
      errorData.value = {
        total: d.total_errors ?? 0,
        rate: d.error_rate ?? 0,
        top_errors: (d.by_type ?? []).map((e: any) => ({ code: e.type, message: e.type, count: e.count })),
      }
    }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.analytics-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
.chart-placeholder { display: flex; align-items: flex-end; gap: 6px; min-height: 180px; padding: 12px 0; }
.chart-bar-wrapper { display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1; }
.chart-bar { width: 100%; max-width: 40px; background: linear-gradient(180deg, #6366f1, #8b5cf6); border-radius: 4px 4px 0 0; min-height: 4px; transition: height 0.3s; }
.chart-label { font-size: 10px; color: var(--nr-text-muted); }
.feature-item { display: flex; justify-content: space-between; width: 100%; align-items: center; }
.path-item { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-secondary); }
</style>
