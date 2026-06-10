<template>
  <div class="trajectory-page">
    <div class="page-header">
      <h2 class="page-title">Agent Trajectory</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchTraces">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <a-spin :spinning="loading">
      <div class="two-col">
        <!-- Trace list with timeline -->
        <GlassCard :title="t('memory.timeline')">
          <a-list :data-source="traces" :loading="loading" size="small">
            <template #renderItem="{ item }">
              <a-list-item class="trace-list-item" :class="{ selected: selectedTrace?.id === item.id }" @click="selectTrace(item)">
                <div class="trace-summary">
                  <div class="trace-top">
                    <a-tag :color="statusColor(item.status)">{{ item.status }}</a-tag>
                    <span class="trace-time">{{ formatTime(item.started_at || item.timestamp) }}</span>
                  </div>
                  <span class="trace-id">{{ item.name || item.id }}</span>
                  <span class="trace-meta">{{ item.steps_count ?? 0 }} steps · {{ item.duration_ms ?? 0 }}ms</span>
                </div>
              </a-list-item>
            </template>
            <template #empty><a-empty :description="t('common.noData')" /></template>
          </a-list>
        </GlassCard>

        <!-- Trace detail -->
        <GlassCard :title="selectedTrace ? `Trace: ${selectedTrace.name || selectedTrace.id}` : 'Select a trace'">
          <template v-if="detailLoading" #default>
            <a-spin />
          </template>
          <template v-if="selectedTrace && !detailLoading">
            <div class="trace-detail">
              <a-descriptions :column="1" size="small" bordered>
                <a-descriptions-item label="ID">{{ selectedTrace.id }}</a-descriptions-item>
                <a-descriptions-item :label="t('common.status')">
                  <a-tag :color="statusColor(selectedTrace.status)">{{ selectedTrace.status }}</a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="Duration">{{ selectedTrace.duration_ms ?? 0 }}ms</a-descriptions-item>
                <a-descriptions-item label="Steps">{{ selectedTrace.steps_count ?? 0 }}</a-descriptions-item>
                <a-descriptions-item label="Started">{{ formatTime(selectedTrace.started_at) }}</a-descriptions-item>
              </a-descriptions>

              <h4 class="detail-section-title">Events</h4>
              <a-timeline>
                <a-timeline-item v-for="(event, i) in traceEvents" :key="i" :color="eventColor(event.type)">
                  <div class="event-item">
                    <span class="event-type">{{ event.type }}</span>
                    <span class="event-time">{{ formatTime(event.timestamp) }}</span>
                  </div>
                  <p v-if="event.message" class="event-message">{{ event.message }}</p>
                </a-timeline-item>
              </a-timeline>
              <a-empty v-if="!traceEvents.length" :description="t('common.noData')" />
            </div>
          </template>
          <a-empty v-if="!selectedTrace" description="Select a trace to view details" />
          <template #footer>
            <GlassButton v-if="selectedTrace" variant="secondary" size="sm" @click="exportTrace">{{ t('common.export') }}</GlassButton>
          </template>
        </GlassCard>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()
const route = useRoute()
const agentId = route.params.agentId as string

const loading = ref(false)
const detailLoading = ref(false)
const traces = ref<any[]>([])
const selectedTrace = ref<any>(null)
const traceEvents = ref<any[]>([])

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const statusColor = (status: string) => {
  const map: Record<string, string> = { completed: 'green', running: 'blue', failed: 'red', pending: 'default' }
  return map[status] || 'default'
}

const eventColor = (type: string) => {
  const map: Record<string, string> = { tool_call: 'blue', llm_call: 'purple', error: 'red', input: 'cyan', output: 'green' }
  return map[type] || 'gray'
}

const fetchTraces = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/trace', { params: { agent_id: agentId } })
    const data = res?.data ?? res ?? {}
    traces.value = data.items ?? data.traces ?? (Array.isArray(data) ? data : [])
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const selectTrace = async (trace: any) => {
  selectedTrace.value = trace
  detailLoading.value = true
  try {
    const res: any = await request.get(`/trace/${trace.id}`)
    const data = res?.data ?? res ?? {}
    selectedTrace.value = { ...trace, ...data }
    traceEvents.value = data.events ?? data.steps ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    detailLoading.value = false
  }
}

const exportTrace = async () => {
  if (!selectedTrace.value) return
  try {
    const res: any = await request.get(`/trace/${selectedTrace.value.id}/export`, { responseType: 'blob' })
    const blob = new Blob([res], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `trace-${selectedTrace.value.id}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

onMounted(fetchTraces)
</script>

<style scoped>
.trajectory-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }
.two-col { display: grid; grid-template-columns: 350px 1fr; gap: 16px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
.trace-list-item { cursor: pointer; transition: background 0.2s; padding: 8px; border-radius: 8px; }
.trace-list-item:hover { background: rgba(255,255,255,0.04); }
.trace-list-item.selected { background: rgba(99,102,241,0.1); }
.trace-summary { display: flex; flex-direction: column; gap: 4px; }
.trace-top { display: flex; justify-content: space-between; align-items: center; }
.trace-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.trace-id { font-weight: 500; color: var(--nr-text-primary); font-size: 13px; }
.trace-meta { font-size: 11px; color: var(--nr-text-tertiary); font-family: var(--nr-font-mono); }
.trace-detail { display: flex; flex-direction: column; gap: 16px; }
.detail-section-title { font-size: 14px; font-weight: 600; color: var(--nr-text-primary); margin: 8px 0 0; }
.event-item { display: flex; justify-content: space-between; align-items: center; }
.event-type { font-weight: 500; color: var(--nr-text-primary); font-size: 12px; text-transform: capitalize; }
.event-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.event-message { font-size: 12px; color: var(--nr-text-tertiary); margin: 2px 0 0; }
</style>
