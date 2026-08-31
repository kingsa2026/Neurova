<template>
  <div class="sleep-status-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('sleep.title') }}</h2>
        <p v-if="currentAgent?.name" class="page-subtitle">{{ currentAgent.name }}</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="pollingLoading" @click="manualRefresh">
          {{ t('common.refresh') }}
        </GlassButton>
        <GlassButton
          v-if="!sleepStatus?.is_sleeping"
          variant="secondary"
          size="sm"
          :loading="actionLoading"
          @click="goToSleep"
        >
          {{ t('sleep.sleepAction') }}
        </GlassButton>
        <GlassButton
          v-else
          variant="primary"
          size="sm"
          :loading="actionLoading"
          @click="wakeUpAgent"
        >
          {{ t('sleep.wake') }}
        </GlassButton>
      </div>
    </div>

    <!-- Current sleep state -->
    <GlassPanel :variant="sleepStatus?.is_sleeping ? 'prominent' : 'subtle'" :glow="sleepStatus?.is_sleeping">
      <div class="sleep-state">
        <div class="sleep-icon">{{ sleepStatus?.is_sleeping ? '🌙' : '☀️' }}</div>
        <div class="sleep-info">
          <h3>{{ sleepStatus?.is_sleeping ? t('sleep.sleeping') : t('sleep.awake') }}</h3>
          <p v-if="sleepStatus?.sleep_phase" class="sleep-phase">
            {{ t('sleep.phase') }}: {{ formatPhase(sleepStatus.sleep_phase) }}
          </p>
          <p v-if="sleepStatus?.started_at" class="sleep-time">
            {{ t('sleep.lastSleep') }}{{ formatTime(sleepStatus.started_at) }}
          </p>
          <p v-if="sleepStatus?.duration_seconds" class="sleep-time">
            {{ t('sleep.duration') }}: {{ formatDuration(sleepStatus.duration_seconds) }}
          </p>
          <p v-if="sleepStatus?.next_wake" class="sleep-time">
            {{ t('sleep.nextWake') }}: {{ formatTime(sleepStatus.next_wake) }}
          </p>
        </div>
      </div>

      <!-- Sleep phase visualization -->
      <div v-if="sleepStatus?.is_sleeping && sleepStatus?.sleep_phase" class="phase-visualization">
        <div class="phase-steps">
          <div
            v-for="phase in sleepPhases"
            :key="phase.key"
            class="phase-step"
            :class="{ active: phase.key === sleepStatus?.sleep_phase, completed: isPhaseCompleted(phase.key) }"
          >
            <div class="phase-dot"></div>
            <span class="phase-name">{{ phase.label }}</span>
          </div>
          <div class="phase-line"></div>
        </div>
      </div>
    </GlassPanel>

    <a-spin :spinning="initialLoading">
      <div class="two-col" style="margin-top: 20px">
        <!-- Dream logs -->
        <GlassCard :title="t('sleep.dreams')">
          <template #extra>
            <a-select
              v-model:value="dreamTypeFilter"
              :placeholder="t('common.all')"
              allow-clear
              size="small"
              style="width: 140px"
              @change="onDreamFilterChange"
            >
              <a-select-option value="consolidation">{{ t('sleep.consolidation') }}</a-select-option>
              <a-select-option value="creative">{{ t('sleep.creative') }}</a-select-option>
              <a-select-option value="problem_solving">{{ t('sleep.problemSolving') }}</a-select-option>
            </a-select>
          </template>
          <a-spin :spinning="dreamsLoading">
            <a-list v-if="dreams.length > 0" :data-source="dreams" size="small">
              <template #renderItem="{ item }">
                <a-list-item>
                  <div class="dream-item">
                    <div class="dream-header">
                      <a-tag :color="dreamTypeColor(item.type)" size="small">{{ formatDreamType(item.type) }}</a-tag>
                      <span class="dream-time">{{ formatTime(item.created_at) }}</span>
                    </div>
                    <p class="dream-content">{{ item.content }}</p>
                    <div v-if="item.insights?.length" class="dream-insights">
                      <a-tag v-for="(insight, idx) in item.insights" :key="idx" size="small" color="geekblue">
                        {{ insight }}
                      </a-tag>
                    </div>
                  </div>
                </a-list-item>
              </template>
            </a-list>
            <a-empty v-else :description="t('common.noData')" />
          </a-spin>
        </GlassCard>

        <!-- Insights -->
        <GlassCard :title="t('sleep.insights')">
          <a-spin :spinning="insightsLoading">
            <a-list v-if="insights.length > 0" :data-source="insights" size="small">
              <template #renderItem="{ item }">
                <a-list-item>
                  <div class="insight-item">
                    <div class="insight-header">
                      <a-tag :color="item.applied ? 'green' : 'blue'">
                        {{ item.applied ? t('sleep.applied') : t('sleep.pending') }}
                      </a-tag>
                      <span class="insight-time">{{ formatTime(item.created_at) }}</span>
                    </div>
                    <p class="insight-content">{{ item.content }}</p>
                    <GlassButton
                      v-if="!item.applied"
                      variant="ghost"
                      size="sm"
                      :loading="applyingInsightId === item.id"
                      @click="handleApplyInsight(item.id)"
                    >
                      {{ t('sleep.applyInsight') }}
                    </GlassButton>
                  </div>
                </a-list-item>
              </template>
            </a-list>
            <a-empty v-else :description="t('common.noData')" />
          </a-spin>
        </GlassCard>
      </div>

      <!-- Memory merges and conflicts -->
      <div class="two-col" style="margin-top: 16px">
        <GlassCard :title="t('sleep.merges')">
          <a-list :data-source="[]" size="small">
            <template #empty><a-empty :description="t('common.noData')" /></template>
          </a-list>
        </GlassCard>

        <GlassCard :title="t('sleep.conflicts')">
          <a-spin :spinning="conflictsLoading">
            <a-list v-if="conflicts.length > 0" :data-source="conflicts" size="small">
              <template #renderItem="{ item }">
                <a-list-item>
                  <div class="conflict-item">
                    <div class="conflict-info">
                      <span class="conflict-field">{{ item.field }}</span>
                      <a-tag :color="item.resolved ? 'green' : 'red'" size="small">
                        {{ item.resolved ? t('sleep.resolved') : t('sleep.pending') }}
                      </a-tag>
                    </div>
                    <div class="conflict-values">
                      <span class="conflict-local">{{ t('sleep.localValue') }}: {{ item.local_value }}</span>
                      <span class="conflict-remote">{{ t('sleep.remoteValue') }}: {{ item.remote_value }}</span>
                    </div>
                    <div v-if="!item.resolved" class="conflict-actions">
                      <a-space>
                        <GlassButton variant="ghost" size="sm" @click="handleResolve(item.id, 'local')">
                          {{ t('sleep.keepLocal') }}
                        </GlassButton>
                        <GlassButton variant="ghost" size="sm" @click="handleResolve(item.id, 'remote')">
                          {{ t('sleep.keepRemote') }}
                        </GlassButton>
                      </a-space>
                    </div>
                    <div v-if="item.resolution" class="conflict-resolution">
                      <a-tag color="green">{{ item.resolution }}</a-tag>
                    </div>
                  </div>
                </a-list-item>
              </template>
            </a-list>
            <a-empty v-else :description="t('common.noData')" />
          </a-spin>
        </GlassCard>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { usePolling } from '@/composables/usePolling'
import * as sleepApi from '@/api/modules/sleep'
import type { SleepStatus, Dream, SleepInsight, MergeConflict } from '@/api/modules/sleep'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()

// --- State ---
const initialLoading = ref(false)
const actionLoading = ref(false)
const dreamsLoading = ref(false)
const insightsLoading = ref(false)
const conflictsLoading = ref(false)
const applyingInsightId = ref<string | null>(null)

const sleepStatus = ref<SleepStatus | null>(null)
const dreams = ref<Dream[]>([])
const insights = ref<SleepInsight[]>([])
const conflicts = ref<MergeConflict[]>([])
const dreamTypeFilter = ref<string | undefined>(undefined)

// --- Sleep phases for visualization ---
const sleepPhases = computed(() => [
  { key: 'light', label: t('sleep.lightPhase') },
  { key: 'deep', label: t('sleep.deepPhase') },
  { key: 'rem', label: t('sleep.remPhase') },
])

const isPhaseCompleted = (phaseKey: string) => {
  const order = ['light', 'deep', 'rem']
  const currentIdx = order.indexOf(sleepStatus.value?.sleep_phase || '')
  const phaseIdx = order.indexOf(phaseKey)
  return phaseIdx < currentIdx
}

// --- Polling for real-time status ---
const {
  loading: pollingLoading,
  start: startPolling,
  stop: stopPolling,
  poll: pollStatus,
} = usePolling(async () => {
  const res = await sleepApi.getSleepStatus(agentId.value)
  const data = sleepApi.unwrapSleep<SleepStatus>(res)
  if (data) {
    sleepStatus.value = data as SleepStatus
  }
  return data
}, 15000) // poll every 15 seconds

// --- Helpers ---
const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const formatDuration = (seconds: number) => {
  if (!seconds) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const parts: string[] = []
  if (h > 0) parts.push(`${h}h`)
  if (m > 0) parts.push(`${m}m`)
  if (s > 0 && h === 0) parts.push(`${s}s`)
  return parts.join(' ')
}

const formatPhase = (phase: string) => {
  const map: Record<string, string> = {
    light: t('sleep.lightPhase'),
    deep: t('sleep.deepPhase'),
    rem: t('sleep.remPhase'),
  }
  return map[phase] || phase
}

const formatDreamType = (type: string) => {
  const map: Record<string, string> = {
    consolidation: t('sleep.consolidation'),
    creative: t('sleep.creative'),
    problem_solving: t('sleep.problemSolving'),
  }
  return map[type] || type
}

const dreamTypeColor = (type: string) => {
  const map: Record<string, string> = {
    consolidation: 'blue',
    creative: 'purple',
    problem_solving: 'green',
  }
  return map[type] || 'default'
}

// --- Fetchers ---
const fetchAll = async () => {
  initialLoading.value = true
  try {
    await Promise.all([fetchStatus(), fetchDreams(), fetchInsights(), fetchConflicts()])
  } finally {
    initialLoading.value = false
  }
}

const fetchStatus = async () => {
  try {
    const res = await sleepApi.getSleepStatus(agentId.value)
    const data = sleepApi.unwrapSleep<SleepStatus>(res)
    if (data) sleepStatus.value = data as SleepStatus
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  }
}

const fetchDreams = async () => {
  dreamsLoading.value = true
  try {
    const params: { page?: number; size?: number; type?: string } = { page: 1, size: 20 }
    if (dreamTypeFilter.value) params.type = dreamTypeFilter.value
    const res = await sleepApi.getDreams(agentId.value, params)
    const data = sleepApi.unwrapSleep<Dream[] | { items: Dream[] }>(res)
    if (data && typeof data === 'object' && 'items' in (data as object)) {
      dreams.value = (data as any).items || []
    } else if (Array.isArray(data)) {
      dreams.value = data
    } else {
      dreams.value = []
    }
  } catch {
    dreams.value = []
  } finally {
    dreamsLoading.value = false
  }
}

const fetchInsights = async () => {
  insightsLoading.value = true
  try {
    const res = await sleepApi.getSleepInsights(agentId.value, { limit: 20, offset: 0 })
    const data = sleepApi.unwrapSleep<SleepInsight[] | { items: SleepInsight[] }>(res)
    if (data && typeof data === 'object' && 'items' in (data as object)) {
      insights.value = (data as any).items || []
    } else if (Array.isArray(data)) {
      insights.value = data
    } else {
      insights.value = []
    }
  } catch {
    insights.value = []
  } finally {
    insightsLoading.value = false
  }
}

const fetchConflicts = async () => {
  conflictsLoading.value = true
  try {
    const res = await sleepApi.getMergeConflicts(agentId.value)
    const data = sleepApi.unwrapSleep<MergeConflict[]>(res)
    conflicts.value = Array.isArray(data) ? data : []
  } catch {
    conflicts.value = []
  } finally {
    conflictsLoading.value = false
  }
}

// --- Actions ---
const wakeUpAgent = async () => {
  actionLoading.value = true
  try {
    await sleepApi.wakeUp(agentId.value)
    message.success(t('common.success'))
    await fetchStatus()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    actionLoading.value = false
  }
}

const goToSleep = async () => {
  actionLoading.value = true
  try {
    await sleepApi.putToSleep(agentId.value)
    message.success(t('common.success'))
    await fetchStatus()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    actionLoading.value = false
  }
}

const handleApplyInsight = async (insightId: string) => {
  applyingInsightId.value = insightId
  try {
    await sleepApi.applyInsight(agentId.value, insightId)
    message.success(t('common.success'))
    // Update the insight locally
    const insight = insights.value.find((i) => i.id === insightId)
    if (insight) insight.applied = true
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    applyingInsightId.value = null
  }
}

const handleResolve = async (conflictId: string, resolution: string) => {
  try {
    await sleepApi.resolveConflict(agentId.value, conflictId, resolution)
    message.success(t('common.success'))
    // Refresh conflicts
    await fetchConflicts()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  }
}

const onDreamFilterChange = () => {
  fetchDreams()
}

const manualRefresh = async () => {
  await Promise.all([pollStatus(), fetchDreams(), fetchInsights(), fetchConflicts()])
}

onMounted(() => {
  fetchAll()
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.sleep-status-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-subtitle { margin: 4px 0 0; color: var(--nr-text-secondary); font-size: 13px; }
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

/* Phase visualization */
.phase-visualization {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--nr-border-secondary, rgba(255, 255, 255, 0.06));
}
.phase-steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  position: relative;
}
.phase-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 1;
  flex: 0 0 auto;
  padding: 0 24px;
}
.phase-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--nr-bg-elevated, rgba(255, 255, 255, 0.08));
  border: 2px solid var(--nr-border-secondary, rgba(255, 255, 255, 0.12));
  transition: all 0.3s ease;
}
.phase-step.active .phase-dot {
  background: var(--nr-primary);
  border-color: var(--nr-primary);
  box-shadow: 0 0 8px rgba(99, 102, 241, 0.5);
}
.phase-step.completed .phase-dot {
  background: var(--nr-success);
  border-color: var(--nr-success);
}
.phase-name {
  font-size: 11px;
  color: var(--nr-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.phase-step.active .phase-name {
  color: var(--nr-primary);
  font-weight: 600;
}
.phase-step.completed .phase-name {
  color: var(--nr-success);
}
.phase-line {
  position: absolute;
  top: 6px;
  left: 25%;
  right: 25%;
  height: 2px;
  background: var(--nr-border-secondary, rgba(255, 255, 255, 0.08));
  z-index: 0;
}

/* Dream items */
.dream-item { display: flex; flex-direction: column; gap: 6px; }
.dream-header { display: flex; justify-content: space-between; align-items: center; }
.dream-type { font-weight: 500; color: var(--nr-text-primary); text-transform: capitalize; }
.dream-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.dream-content { font-size: 13px; color: var(--nr-text-secondary); margin: 0; }
.dream-insights { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }

/* Insight items */
.insight-item { display: flex; flex-direction: column; gap: 6px; }
.insight-header { display: flex; justify-content: space-between; align-items: center; }
.insight-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.insight-content { font-size: 13px; color: var(--nr-text-secondary); margin: 4px 0 0; }

/* Conflict items */
.conflict-item { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.conflict-info { display: flex; justify-content: space-between; align-items: center; }
.conflict-field { font-weight: 500; color: var(--nr-text-primary); font-size: 13px; }
.conflict-values { display: flex; flex-direction: column; gap: 2px; }
.conflict-local, .conflict-remote { font-size: 11px; color: var(--nr-text-secondary); font-family: var(--nr-font-mono); }
.conflict-actions { margin-top: 4px; }
.conflict-resolution { margin-top: 4px; }
</style>
