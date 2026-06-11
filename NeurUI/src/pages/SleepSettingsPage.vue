<template>
  <div class="sleep-settings-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('sleep.settings') }}</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchSettings">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <a-spin :spinning="loading">
      <!-- Core settings -->
      <GlassCard :title="t('sleep.status')" style="margin-top: 8px">
        <a-form layout="vertical" :model="settingsForm">
          <a-form-item :label="t('sleep.enableAutoSleep')">
            <a-switch v-model:checked="settingsForm.auto_sleep" />
          </a-form-item>
          <a-form-item :label="t('sleep.enabled')">
            <a-switch v-model:checked="settingsForm.enabled" />
          </a-form-item>
          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item :label="t('sleep.scheduleStart')" :rules="[{ required: true }]">
                <a-time-picker
                  v-model:value="settingsForm.schedule_start"
                  format="HH:mm"
                  style="width: 100%"
                  :placeholder="t('sleep.scheduleStartPlaceholder')"
                />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item :label="t('sleep.scheduleEnd')" :rules="[{ required: true }]">
                <a-time-picker
                  v-model:value="settingsForm.schedule_end"
                  format="HH:mm"
                  style="width: 100%"
                  :placeholder="t('sleep.scheduleEndPlaceholder')"
                />
              </a-form-item>
            </a-col>
          </a-row>
          <a-form-item :label="t('sleep.minInterval')">
            <a-input-number
              v-model:value="settingsForm.min_interval_hours"
              :min="1"
              :max="168"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.hours')"
            />
          </a-form-item>
          <a-form-item :label="t('sleep.enableDreaming')">
            <a-switch v-model:checked="settingsForm.dream_enabled" />
          </a-form-item>
        </a-form>
        <template #footer>
          <div class="form-actions">
            <GlassButton
              variant="primary"
              size="sm"
              :loading="saveMutation.loading.value"
              @click="handleSave"
            >
              {{ t('common.save') }}
            </GlassButton>
            <GlassButton variant="ghost" size="sm" @click="fetchSettings">
              {{ t('common.reset') }}
            </GlassButton>
          </div>
        </template>
      </GlassCard>

      <!-- Legacy schedule section (preserved from original) -->
      <GlassCard :title="t('sleep.sleepTime')" style="margin-top: 16px">
        <a-form layout="vertical" :model="schedule">
          <a-form-item :label="t('sleep.enableAutoSleep')">
            <a-switch v-model:checked="schedule.enabled" />
          </a-form-item>
          <a-form-item :label="t('sleep.sleepTime')">
            <a-time-picker v-model:value="schedule.sleep_time" format="HH:mm" style="width: 100%" />
          </a-form-item>
          <a-form-item :label="t('sleep.wakeTime')">
            <a-time-picker v-model:value="schedule.wake_time" format="HH:mm" style="width: 100%" />
          </a-form-item>
          <a-form-item :label="t('sleep.maxDuration')">
            <a-input-number v-model:value="schedule.max_duration_hours" :min="1" :max="24" style="width: 100%" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saveMutation.loading.value" @click="handleSave">
            {{ t('common.save') }}
          </GlassButton>
        </template>
      </GlassCard>

      <!-- Dream parameters -->
      <GlassCard :title="t('sleep.dreams')" style="margin-top: 16px">
        <a-form layout="vertical" :model="dreams">
          <a-form-item :label="t('sleep.enableDreaming')">
            <a-switch v-model:checked="dreams.enabled" />
          </a-form-item>
          <a-form-item :label="t('sleep.dreamFrequency')">
            <a-select v-model:value="dreams.frequency" style="width: 100%">
              <a-select-option value="every_sleep">{{ t('sleep.everySleep') }}</a-select-option>
              <a-select-option value="random">{{ t('sleep.random') }}</a-select-option>
              <a-select-option value="never">{{ t('sleep.never') }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item :label="t('sleep.dreamDepth')">
            <a-slider v-model:value="dreams.depth" :min="1" :max="10" />
          </a-form-item>
          <a-form-item :label="t('sleep.maxDreamTopics')">
            <a-input-number v-model:value="dreams.max_topics" :min="1" :max="20" style="width: 100%" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saveMutation.loading.value" @click="handleSave">
            {{ t('common.save') }}
          </GlassButton>
        </template>
      </GlassCard>

      <!-- Memory merge settings -->
      <GlassCard :title="t('sleep.merges')" style="margin-top: 16px">
        <a-form layout="vertical" :model="memoryMerge">
          <a-form-item :label="t('sleep.enableMemoryMerge')">
            <a-switch v-model:checked="memoryMerge.enabled" />
          </a-form-item>
          <a-form-item :label="t('sleep.mergeStrategy')">
            <a-select v-model:value="memoryMerge.strategy" style="width: 100%">
              <a-select-option value="conservative">{{ t('sleep.conservative') }}</a-select-option>
              <a-select-option value="balanced">{{ t('sleep.balanced') }}</a-select-option>
              <a-select-option value="aggressive">{{ t('sleep.aggressive') }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item :label="t('sleep.conflictResolution')">
            <a-select v-model:value="memoryMerge.conflict_resolution" style="width: 100%">
              <a-select-option value="keep_newest">{{ t('sleep.keepNewest') }}</a-select-option>
              <a-select-option value="keep_strongest">{{ t('sleep.keepStrongest') }}</a-select-option>
              <a-select-option value="merge">{{ t('sleep.mergeOption') }}</a-select-option>
              <a-select-option value="flag">{{ t('sleep.flagForReview') }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item :label="t('sleep.similarityThreshold')">
            <a-slider v-model:value="memoryMerge.similarity_threshold" :min="0" :max="100" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saveMutation.loading.value" @click="handleSave">
            {{ t('common.save') }}
          </GlassButton>
        </template>
      </GlassCard>

      <!-- Merge Conflicts -->
      <GlassCard :title="t('sleep.conflicts')" style="margin-top: 16px">
        <template #extra>
          <GlassButton variant="ghost" size="sm" :loading="conflictsLoading" @click="fetchConflicts">
            {{ t('common.refresh') }}
          </GlassButton>
        </template>
        <a-spin :spinning="conflictsLoading">
          <div v-if="conflicts.length > 0" class="conflicts-list">
            <div v-for="conflict in conflicts" :key="conflict.id" class="conflict-card">
              <div class="conflict-header">
                <span class="conflict-field">{{ conflict.field }}</span>
                <a-tag :color="conflict.resolved ? 'green' : 'red'" size="small">
                  {{ conflict.resolved ? t('sleep.resolved') : t('sleep.pending') }}
                </a-tag>
              </div>
              <div class="conflict-body">
                <div class="conflict-value-row">
                  <div class="conflict-value">
                    <span class="value-label">{{ t('sleep.localValue') }}</span>
                    <code class="value-code">{{ conflict.local_value }}</code>
                  </div>
                  <div class="conflict-value">
                    <span class="value-label">{{ t('sleep.remoteValue') }}</span>
                    <code class="value-code">{{ conflict.remote_value }}</code>
                  </div>
                </div>
              </div>
              <div v-if="!conflict.resolved" class="conflict-actions">
                <a-space>
                  <GlassButton
                    variant="ghost"
                    size="sm"
                    :loading="resolvingId === conflict.id"
                    @click="handleResolve(conflict.id, 'local')"
                  >
                    {{ t('sleep.keepLocal') }}
                  </GlassButton>
                  <GlassButton
                    variant="ghost"
                    size="sm"
                    :loading="resolvingId === conflict.id"
                    @click="handleResolve(conflict.id, 'remote')"
                  >
                    {{ t('sleep.keepRemote') }}
                  </GlassButton>
                  <GlassButton
                    variant="ghost"
                    size="sm"
                    :loading="resolvingId === conflict.id"
                    @click="showCustomResolve(conflict)"
                  >
                    {{ t('sleep.customResolve') }}
                  </GlassButton>
                </a-space>
              </div>
              <div v-if="conflict.resolution" class="conflict-resolution">
                <a-tag color="green">{{ conflict.resolution }}</a-tag>
                <span class="resolution-time">{{ formatTime(conflict.created_at) }}</span>
              </div>
            </div>
          </div>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </GlassCard>
    </a-spin>

    <!-- Custom resolve modal -->
    <a-modal
      v-model:open="showResolveModal"
      :title="t('sleep.customResolve')"
      :confirm-loading="resolvingId !== null"
      @ok="handleCustomResolve"
      @cancel="customResolveValue = ''"
    >
      <p v-if="customResolveConflict" class="resolve-modal-info">
        {{ t('sleep.conflictField') }}: <strong>{{ customResolveConflict.field }}</strong>
      </p>
      <a-form layout="vertical">
        <a-form-item :label="t('sleep.resolutionValue')">
          <a-textarea
            v-model:value="customResolveValue"
            :rows="3"
            :placeholder="t('sleep.resolutionPlaceholder')"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useMutation } from '@/composables/useAPI'
import * as sleepApi from '@/api/modules/sleep'
import type { SleepSettings, MergeConflict } from '@/api/modules/sleep'

const { t } = useI18n()
const { agentId } = useAgentPage()

// --- State ---
const loading = ref(false)
const conflictsLoading = ref(false)
const resolvingId = ref<string | null>(null)
const conflicts = ref<MergeConflict[]>([])

// --- API-backed settings form ---
const settingsForm = reactive<{
  enabled: boolean
  schedule_start: string
  schedule_end: string
  min_interval_hours: number
  auto_sleep: boolean
  dream_enabled: boolean
}>({
  enabled: true,
  schedule_start: '',
  schedule_end: '',
  min_interval_hours: 6,
  auto_sleep: false,
  dream_enabled: true,
})

// --- Legacy form models (preserved) ---
const schedule = ref({ enabled: true, sleep_time: null as any, wake_time: null as any, max_duration_hours: 8 })
const dreams = ref({ enabled: true, frequency: 'random', depth: 5, max_topics: 5 })
const memoryMerge = ref({ enabled: true, strategy: 'balanced', conflict_resolution: 'keep_newest', similarity_threshold: 70 })

// --- Custom resolve modal ---
const showResolveModal = ref(false)
const customResolveValue = ref('')
const customResolveConflict = ref<MergeConflict | null>(null)

// --- Mutation for save ---
const saveMutation = useMutation<Partial<SleepSettings>, SleepSettings>(
  (data) => sleepApi.updateSleepSettings(agentId.value, data),
)

// --- Helpers ---
const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

// --- Fetchers ---
const fetchSettings = async () => {
  loading.value = true
  try {
    const res = await sleepApi.getSleepSettings(agentId.value)
    const data = res?.data
    if (data && typeof data === 'object') {
      const settings = data as SleepSettings
      settingsForm.enabled = settings.enabled ?? settingsForm.enabled
      settingsForm.schedule_start = settings.schedule_start ?? settingsForm.schedule_start
      settingsForm.schedule_end = settings.schedule_end ?? settingsForm.schedule_end
      settingsForm.min_interval_hours = settings.min_interval_hours ?? settingsForm.min_interval_hours
      settingsForm.auto_sleep = settings.auto_sleep ?? settingsForm.auto_sleep
      settingsForm.dream_enabled = settings.dream_enabled ?? settingsForm.dream_enabled

      // Also populate legacy forms if available
      if (settings.schedule_start) {
        schedule.value.sleep_time = settings.schedule_start as any
      }
      if (settings.schedule_end) {
        schedule.value.wake_time = settings.schedule_end as any
      }
      schedule.value.enabled = settings.auto_sleep ?? schedule.value.enabled
      dreams.value.enabled = settings.dream_enabled ?? dreams.value.enabled
    }
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchConflicts = async () => {
  conflictsLoading.value = true
  try {
    const res = await sleepApi.getMergeConflicts(agentId.value)
    const data = res?.data
    conflicts.value = Array.isArray(data) ? data : []
  } catch {
    conflicts.value = []
  } finally {
    conflictsLoading.value = false
  }
}

// --- Actions ---
const handleSave = async () => {
  // Validation
  if (settingsForm.min_interval_hours < 1 || settingsForm.min_interval_hours > 168) {
    message.warning(t('sleep.minIntervalValidation'))
    return
  }

  const payload: Partial<SleepSettings> = {
    enabled: settingsForm.enabled,
    schedule_start: settingsForm.schedule_start,
    schedule_end: settingsForm.schedule_end,
    min_interval_hours: settingsForm.min_interval_hours,
    auto_sleep: settingsForm.auto_sleep,
    dream_enabled: settingsForm.dream_enabled,
  }

  const result = await saveMutation.execute(payload)
  if (result) {
    message.success(t('common.success'))
    await fetchSettings()
  } else if (saveMutation.error.value) {
    message.error(saveMutation.error.value)
  }
}

const handleResolve = async (conflictId: string, resolution: string) => {
  resolvingId.value = conflictId
  try {
    await sleepApi.resolveConflict(conflictId, resolution)
    message.success(t('common.success'))
    await fetchConflicts()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    resolvingId.value = null
  }
}

const showCustomResolve = (conflict: MergeConflict) => {
  customResolveConflict.value = conflict
  customResolveValue.value = ''
  showResolveModal.value = true
}

const handleCustomResolve = async () => {
  if (!customResolveValue.value.trim()) {
    message.warning(t('sleep.resolutionRequired'))
    return
  }
  if (!customResolveConflict.value) return
  resolvingId.value = customResolveConflict.value.id
  try {
    await sleepApi.resolveConflict(customResolveConflict.value.id, customResolveValue.value)
    message.success(t('common.success'))
    showResolveModal.value = false
    customResolveValue.value = ''
    customResolveConflict.value = null
    await fetchConflicts()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    resolvingId.value = null
  }
}

onMounted(() => {
  fetchSettings()
  fetchConflicts()
})
</script>

<style scoped>
.sleep-settings-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }

.form-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Conflicts */
.conflicts-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.conflict-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--nr-border-secondary, rgba(255, 255, 255, 0.06));
  border-radius: 8px;
  background: var(--nr-bg-elevated, rgba(255, 255, 255, 0.02));
}

.conflict-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.conflict-field {
  font-weight: 600;
  color: var(--nr-text-primary);
  font-size: 13px;
}

.conflict-body {
  padding: 4px 0;
}

.conflict-value-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.conflict-value {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.value-label {
  font-size: 10px;
  color: var(--nr-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.value-code {
  font-family: var(--nr-font-mono);
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: rgba(255, 255, 255, 0.04);
  padding: 4px 8px;
  border-radius: 4px;
  word-break: break-all;
}

.conflict-actions {
  padding-top: 4px;
}

.conflict-resolution {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}

.resolution-time {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}

.resolve-modal-info {
  font-size: 13px;
  color: var(--nr-text-secondary);
  margin-bottom: 12px;
}
</style>
