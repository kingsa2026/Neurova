<template>
  <div class="trace-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('nav.trace') }}</h2>
      <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchTraces">{{ t('common.refresh') }}</GlassButton>
    </div>

    <!-- Performance metrics -->
    <GlassCard title="Performance Metrics">
      <div class="metrics-grid">
        <GlassStatCard label="Total Traces" :value="stats.total ?? 0" emoji="📊" />
        <GlassStatCard label="Avg Duration" :value="`${stats.avg_duration_ms ?? 0}ms`" emoji="⏱️" />
        <GlassStatCard label="Success Rate" :value="`${stats.success_rate ?? 0}%`" emoji="✅" />
        <GlassStatCard label="Avg Steps" :value="stats.avg_steps ?? 0" emoji="📈" />
      </div>
    </GlassCard>

    <a-spin :spinning="loading">
      <!-- Execution events timeline -->
      <GlassCard title="Execution Events" style="margin-top: 16px">
        <a-table
          :columns="traceColumns"
          :data-source="traces"
          row-key="id"
          :pagination="{ pageSize: 20 }"
          size="small"
          :expandedRowKeys="expandedKeys"
          @expand="onExpand"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
            </template>
            <template v-if="column.key === 'duration'">
              <span class="mono">{{ record.duration_ms ?? 0 }}ms</span>
            </template>
            <template v-if="column.key === 'timestamp'">
              <span class="mono">{{ formatTime(record.started_at || record.timestamp) }}</span>
            </template>
          </template>
          <template #expandedRowRender="{ record }">
            <div class="expanded-trace">
              <!-- Tool call traces -->
              <h4 class="section-title">Tool Calls</h4>
              <a-list :data-source="record.tool_calls || record.expanded?.tool_calls || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <div class="tool-call-item">
                      <a-tag color="blue">{{ item.tool || item.name }}</a-tag>
                      <span class="tool-duration">{{ item.duration_ms ?? 0 }}ms</span>
                      <a-tag :color="item.success ? 'green' : 'red'" size="small">{{ item.success ? 'OK' : 'FAIL' }}</a-tag>
                    </div>
                  </a-list-item>
                </template>
                <template #empty><span class="text-muted">No tool calls</span></template>
              </a-list>

              <!-- LLM calls -->
              <h4 class="section-title">LLM Calls</h4>
              <a-list :data-source="record.llm_calls || record.expanded?.llm_calls || []" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <div class="llm-call-item">
                      <span class="llm-model">{{ item.model }}</span>
                      <span class="mono">{{ item.tokens_in ?? 0 }} in / {{ item.tokens_out ?? 0 }} out</span>
                      <span class="tool-duration">{{ item.duration_ms ?? 0 }}ms</span>
                    </div>
                  </a-list-item>
                </template>
                <template #empty><span class="text-muted">No LLM calls</span></template>
              </a-list>

              <!-- Performance per trace -->
              <h4 class="section-title">Performance Breakdown</h4>
              <div class="perf-breakdown">
                <div class="perf-item">
                  <span>LLM Time</span>
                  <a-progress :percent="perfPercent(record, 'llm')" size="small" stroke-color="#8b5cf6" />
                </div>
                <div class="perf-item">
                  <span>Tool Time</span>
                  <a-progress :percent="perfPercent(record, 'tool')" size="small" stroke-color="#6366f1" />
                </div>
                <div class="perf-item">
                  <span>Other</span>
                  <a-progress :percent="perfPercent(record, 'other')" size="small" stroke-color="#64748b" />
                </div>
              </div>
            </div>
          </template>
        </a-table>
      </GlassCard>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()
const route = useRoute()
const agentId = route.params.agentId as string

const loading = ref(false)
const traces = ref<any[]>([])
const stats = ref<Record<string, any>>({})
const expandedKeys = ref<string[]>([])

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const statusColor = (status: string) => {
  const map: Record<string, string> = { completed: 'green', running: 'blue', failed: 'red', pending: 'default' }
  return map[status] || 'default'
}

const traceColumns = computed(() => [
  { title: 'ID', dataIndex: 'id', key: 'id', width: 120 },
  { title: 'Name', dataIndex: 'name', key: 'name' },
  { title: t('common.status'), key: 'status', width: 100 },
  { title: 'Duration', key: 'duration', width: 100 },
  { title: 'Steps', dataIndex: 'steps_count', key: 'steps', width: 80 },
  { title: 'Time', key: 'timestamp', width: 160 },
])

const perfPercent = (record: any, type: string) => {
  const total = record.duration_ms || 1
  const breakdown = record.breakdown || record.expanded?.breakdown || {}
  const val = breakdown[`${type}_ms`] || 0
  return Math.min(100, Math.round((val / total) * 100))
}

const fetchTraces = async () => {
  loading.value = true
  try {
    const [traceRes, statsRes]: any[] = await Promise.all([
      request.get('/trace', { params: { agent_id: agentId } }),
      request.get('/trace/stats', { params: { agent_id: agentId } }),
    ])
    const td = traceRes?.data ?? traceRes ?? {}
    traces.value = td.items ?? td.traces ?? (Array.isArray(td) ? td : [])
    stats.value = statsRes?.data ?? statsRes ?? {}
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const onExpand = async (expanded: boolean, record: any) => {
  if (expanded) {
    expandedKeys.value = [record.id]
    if (!record.expanded && !record.tool_calls) {
      try {
        const res: any = await request.get(`/trace/${record.id}`)
        const data = res?.data ?? res ?? {}
        record.expanded = data
        record.tool_calls = data.tool_calls ?? []
        record.llm_calls = data.llm_calls ?? []
        record.breakdown = data.breakdown ?? {}
      } catch {
        // keep empty
      }
    }
  } else {
    expandedKeys.value = []
  }
}

onMounted(fetchTraces)
</script>

<style scoped>
.trace-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.mono { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-secondary); }
.expanded-trace { padding: 8px 16px; }
.section-title { font-size: 13px; font-weight: 600; color: var(--nr-text-primary); margin: 12px 0 8px; }
.tool-call-item, .llm-call-item { display: flex; align-items: center; gap: 8px; }
.tool-duration { font-family: var(--nr-font-mono); font-size: 11px; color: var(--nr-text-tertiary); }
.llm-model { font-weight: 500; color: var(--nr-text-primary); font-size: 12px; }
.perf-breakdown { display: flex; flex-direction: column; gap: 8px; }
.perf-item { display: flex; align-items: center; gap: 12px; }
.perf-item span { width: 80px; font-size: 12px; color: var(--nr-text-secondary); }
.text-muted { color: var(--nr-text-muted); font-size: 12px; }
</style>
