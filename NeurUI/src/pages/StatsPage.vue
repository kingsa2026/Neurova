<template>
  <div class="stats-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.stats') }}</h2>
      <GlassButton variant="secondary" size="sm" :loading="exporting" @click="exportStats">{{ t('common.export') }}</GlassButton>
    </div>

    <!-- Overview stat cards -->
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const exporting = ref(false)
const overview = ref<Record<string, any>>({})
const agentStats = ref<any[]>([])
const trends = ref<any[]>([])

const maxTrend = computed(() => Math.max(...trends.value.map((p: any) => p.value || 0), 1))

const agentColumns = computed(() => [
  { title: t('common.name'), key: 'name', dataIndex: 'name' },
  { title: t('common.status'), key: 'status' },
  { title: t('dashboard.totalConversations'), dataIndex: 'conversations', key: 'conversations' },
  { title: t('dashboard.totalTokens'), key: 'tokens' },
  { title: t('dashboard.totalCalls'), dataIndex: 'api_calls', key: 'api_calls' },
  { title: t('system.errors'), dataIndex: 'errors', key: 'errors' },
])

const fetchStats = async () => {
  loading.value = true
  try {
    const [overviewRes, agentsRes]: any[] = await Promise.all([
      request.get('/stats'),
      request.get('/stats/agents'),
    ])
    const ov = overviewRes?.data ?? overviewRes ?? {}
    overview.value = ov.overview ?? ov
    trends.value = ov.trends ?? ov.timeline ?? []

    const ag = agentsRes?.data ?? agentsRes ?? []
    agentStats.value = Array.isArray(ag) ? ag : ag.agents ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const exportStats = async () => {
  exporting.value = true
  try {
    const res: any = await request.get('/stats/export', { responseType: 'blob' })
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

onMounted(fetchStats)
</script>

<style scoped>
.stats-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.agent-name { font-weight: 500; color: var(--nr-text-primary); }
.mono { font-family: var(--nr-font-mono); font-size: 13px; }
.chart-area { display: flex; align-items: flex-end; gap: 6px; min-height: 160px; padding: 12px 0; }
.chart-bar-wrapper { display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1; }
.chart-bar { width: 100%; max-width: 36px; background: linear-gradient(180deg, #6366f1, #8b5cf6); border-radius: 4px 4px 0 0; transition: height 0.3s; }
.chart-label { font-size: 10px; color: var(--nr-text-muted); }
</style>
