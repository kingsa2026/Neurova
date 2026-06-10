<template>
  <div class="analytics-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.analytics') }}</h2>
      <a-radio-group v-model:value="timeRange" button-style="solid" size="small" @change="fetchAll">
        <a-radio-button value="day">Day</a-radio-button>
        <a-radio-button value="week">Week</a-radio-button>
        <a-radio-button value="month">Month</a-radio-button>
      </a-radio-group>
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="fetchAll">
      <!-- Usage tab -->
      <a-tab-pane key="usage" :tab="t('system.usage')">
        <a-spin :spinning="loading">
          <div class="stats-grid">
            <GlassStatCard :label="t('dashboard.totalConversations')" :value="usageData.conversations ?? 0" emoji="💬" :trend="usageData.conversations_trend" />
            <GlassStatCard :label="t('dashboard.totalTokens')" :value="usageData.tokens ?? 0" emoji="🔤" :trend="usageData.tokens_trend" />
            <GlassStatCard :label="t('dashboard.totalCalls')" :value="usageData.api_calls ?? 0" emoji="📡" :trend="usageData.api_calls_trend" />
            <GlassStatCard :label="t('dashboard.totalAgents')" :value="usageData.agents ?? 0" emoji="🤖" :trend="usageData.agents_trend" />
          </div>
          <GlassCard title="Usage Over Time" style="margin-top: 20px">
            <div class="chart-placeholder">
              <div v-for="(point, i) in usageData.timeline ?? []" :key="i" class="chart-bar-wrapper">
                <div class="chart-bar" :style="{ height: `${Math.max(4, (point.value / (usageData.max_value || 1)) * 160)}px` }" />
                <span class="chart-label">{{ point.label }}</span>
              </div>
              <a-empty v-if="!(usageData.timeline?.length)" :description="t('common.noData')" />
            </div>
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Performance tab -->
      <a-tab-pane key="performance" :tab="t('system.performance')">
        <a-spin :spinning="loading">
          <div class="stats-grid">
            <GlassStatCard label="Avg Response" :value="`${perfData.avg_response_ms ?? 0}ms`" emoji="⚡" />
            <GlassStatCard label="P95 Latency" :value="`${perfData.p95_ms ?? 0}ms`" emoji="📊" />
            <GlassStatCard label="Throughput" :value="`${perfData.throughput ?? 0}/s`" emoji="🚀" />
            <GlassStatCard label="Error Rate" :value="`${perfData.error_rate ?? 0}%`" emoji="⚠️" />
          </div>
          <GlassCard title="Response Times" style="margin-top: 20px">
            <a-table :columns="perfColumns" :data-source="perfData.endpoints ?? []" row-key="path" :pagination="false" size="small" />
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Behavior tab -->
      <a-tab-pane key="behavior" tab="Behavior">
        <a-spin :spinning="loading">
          <div class="two-col">
            <GlassCard title="Popular Features">
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
            <GlassCard title="User Paths">
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
            <GlassStatCard label="Total Errors" :value="errorData.total ?? 0" emoji="❌" :trend="errorData.trend" />
            <GlassStatCard label="Error Rate" :value="`${errorData.rate ?? 0}%`" emoji="📉" />
          </div>
          <GlassCard title="Top Errors" style="margin-top: 20px">
            <a-table :columns="errorColumns" :data-source="errorData.top_errors ?? []" row-key="code" :pagination="false" size="small" />
          </GlassCard>
        </a-spin>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const activeTab = ref('usage')
const timeRange = ref('week')
const loading = ref(false)

const usageData = ref<Record<string, any>>({})
const perfData = ref<Record<string, any>>({})
const behaviorData = ref<Record<string, any>>({})
const errorData = ref<Record<string, any>>({})

const perfColumns = computed(() => [
  { title: 'Endpoint', dataIndex: 'path', key: 'path' },
  { title: 'Avg (ms)', dataIndex: 'avg_ms', key: 'avg_ms' },
  { title: 'P95 (ms)', dataIndex: 'p95_ms', key: 'p95_ms' },
  { title: 'Calls', dataIndex: 'count', key: 'count' },
])

const errorColumns = computed(() => [
  { title: 'Code', dataIndex: 'code', key: 'code' },
  { title: 'Message', dataIndex: 'message', key: 'message', ellipsis: true },
  { title: 'Count', dataIndex: 'count', key: 'count' },
])

const fetchAll = async () => {
  loading.value = true
  try {
    const params = { range: timeRange.value }
    if (activeTab.value === 'usage') {
      const res: any = await request.get('/analytics/usage', { params })
      usageData.value = res?.data ?? res ?? {}
    } else if (activeTab.value === 'performance') {
      const res: any = await request.get('/analytics/performance', { params })
      perfData.value = res?.data ?? res ?? {}
    } else if (activeTab.value === 'behavior') {
      const res: any = await request.get('/analytics/behavior', { params })
      behaviorData.value = res?.data ?? res ?? {}
    } else if (activeTab.value === 'errors') {
      const res: any = await request.get('/analytics/errors', { params })
      errorData.value = res?.data ?? res ?? {}
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
