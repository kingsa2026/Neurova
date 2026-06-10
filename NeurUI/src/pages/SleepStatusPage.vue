<template>
  <div class="sleep-status-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('sleep.title') }}</h2>
      <div class="header-actions">
        <GlassButton v-if="!sleepState.is_sleeping" variant="secondary" size="sm" :loading="actionLoading" @click="goToSleep">
          {{ t('sleep.sleepAction') }}
        </GlassButton>
        <GlassButton v-else variant="primary" size="sm" :loading="actionLoading" @click="wakeUp">
          {{ t('sleep.wake') }}
        </GlassButton>
      </div>
    </div>

    <!-- Current sleep state -->
    <GlassPanel :variant="sleepState.is_sleeping ? 'prominent' : 'subtle'" :glow="sleepState.is_sleeping">
      <div class="sleep-state">
        <div class="sleep-icon">{{ sleepState.is_sleeping ? '🌙' : '☀️' }}</div>
        <div class="sleep-info">
          <h3>{{ sleepState.is_sleeping ? 'Sleeping' : 'Awake' }}</h3>
          <p v-if="sleepState.phase" class="sleep-phase">Phase: {{ sleepState.phase }}</p>
          <p v-if="sleepState.last_sleep" class="sleep-time">Last sleep: {{ formatTime(sleepState.last_sleep) }}</p>
          <p v-if="sleepState.duration" class="sleep-time">Duration: {{ sleepState.duration }}</p>
        </div>
      </div>
    </GlassPanel>

    <a-spin :spinning="loading">
      <div class="two-col" style="margin-top: 20px">
        <!-- Dream logs -->
        <GlassCard :title="t('sleep.dreams')">
          <a-list :data-source="dreams" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <div class="dream-item">
                  <div class="dream-header">
                    <span class="dream-type">{{ item.type || 'dream' }}</span>
                    <span class="dream-time">{{ formatTime(item.timestamp) }}</span>
                  </div>
                  <p class="dream-content">{{ item.content || item.summary }}</p>
                </div>
              </a-list-item>
            </template>
            <template #empty><a-empty :description="t('common.noData')" /></template>
          </a-list>
        </GlassCard>

        <!-- Insights -->
        <GlassCard :title="t('sleep.insights')">
          <a-list :data-source="insights" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <div class="insight-item">
                  <a-tag :color="insightColor(item.type)">{{ item.type || 'insight' }}</a-tag>
                  <p class="insight-content">{{ item.content || item.description }}</p>
                </div>
              </a-list-item>
            </template>
            <template #empty><a-empty :description="t('common.noData')" /></template>
          </a-list>
        </GlassCard>
      </div>

      <!-- Memory merges and conflicts -->
      <div class="two-col" style="margin-top: 16px">
        <GlassCard :title="t('sleep.merges')">
          <a-list :data-source="merges" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <div class="merge-item">
                  <span>{{ item.source }} → {{ item.target }}</span>
                  <a-tag :color="item.status === 'completed' ? 'green' : 'orange'">{{ item.status }}</a-tag>
                </div>
              </a-list-item>
            </template>
            <template #empty><a-empty :description="t('common.noData')" /></template>
          </a-list>
        </GlassCard>

        <GlassCard :title="t('sleep.conflicts')">
          <a-list :data-source="conflicts" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <div class="conflict-item">
                  <span>{{ item.description }}</span>
                  <a-tag :color="item.resolved ? 'green' : 'red'">{{ item.resolved ? 'Resolved' : 'Pending' }}</a-tag>
                </div>
              </a-list-item>
            </template>
            <template #empty><a-empty :description="t('common.noData')" /></template>
          </a-list>
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
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()
const route = useRoute()
const agentId = route.params.agentId as string

const loading = ref(false)
const actionLoading = ref(false)
const sleepState = ref<Record<string, any>>({ is_sleeping: false })
const dreams = ref<any[]>([])
const insights = ref<any[]>([])
const merges = ref<any[]>([])
const conflicts = ref<any[]>([])

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const insightColor = (type: string) => {
  const map: Record<string, string> = { pattern: 'blue', anomaly: 'orange', summary: 'green', suggestion: 'purple' }
  return map[type] || 'default'
}

const fetchStatus = async () => {
  loading.value = true
  try {
    const [statusRes, dreamsRes]: any[] = await Promise.all([
      request.get(`/sleep/${agentId}/status`),
      request.get(`/sleep/${agentId}/dreams`),
    ])
    const status = statusRes?.data ?? statusRes ?? {}
    sleepState.value = status

    const dreamData = dreamsRes?.data ?? dreamsRes ?? {}
    dreams.value = dreamData.dreams ?? (Array.isArray(dreamData) ? dreamData : [])
    insights.value = dreamData.insights ?? status.insights ?? []
    merges.value = dreamData.merges ?? status.merges ?? []
    conflicts.value = dreamData.conflicts ?? status.conflicts ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const wakeUp = async () => {
  actionLoading.value = true
  try {
    await request.post(`/sleep/${agentId}/wake`)
    message.success(t('common.success'))
    await fetchStatus()
  } catch {
    message.error(t('common.error'))
  } finally {
    actionLoading.value = false
  }
}

const goToSleep = async () => {
  actionLoading.value = true
  try {
    await request.post(`/sleep/${agentId}/sleep`)
    message.success(t('common.success'))
    await fetchStatus()
  } catch {
    message.error(t('common.error'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(fetchStatus)
</script>

<style scoped>
.sleep-status-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }
.sleep-state { display: flex; align-items: center; gap: 20px; }
.sleep-icon { font-size: 48px; }
.sleep-info { display: flex; flex-direction: column; gap: 4px; }
.sleep-info h3 { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.sleep-phase { font-size: 14px; color: var(--nr-text-secondary); margin: 0; text-transform: capitalize; }
.sleep-time { font-size: 12px; color: var(--nr-text-tertiary); margin: 0; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
.dream-item { display: flex; flex-direction: column; gap: 4px; }
.dream-header { display: flex; justify-content: space-between; }
.dream-type { font-weight: 500; color: var(--nr-text-primary); text-transform: capitalize; }
.dream-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.dream-content { font-size: 13px; color: var(--nr-text-secondary); margin: 0; }
.insight-item { display: flex; flex-direction: column; gap: 4px; }
.insight-content { font-size: 13px; color: var(--nr-text-secondary); margin: 4px 0 0; }
.merge-item, .conflict-item { display: flex; justify-content: space-between; align-items: center; width: 100%; }
</style>
