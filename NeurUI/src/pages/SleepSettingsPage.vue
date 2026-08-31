<template>
  <div class="sleep-settings-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('sleep.settings') }}</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchSettings">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <a-spin :spinning="loading">
      <!-- Core settings（与后端 SleepSettings 键位严格对齐） -->
      <GlassCard :title="t('sleep.settings')" style="margin-top: 8px">
        <a-form layout="vertical" :model="settingsForm">
          <a-form-item :label="t('sleep.enableAutoSleep')">
            <a-switch v-model:checked="settingsForm.auto_sleep_enabled" />
          </a-form-item>
          <a-form-item :label="t('sleep.sleepThresholdMinutes')">
            <a-input-number
              v-model:value="settingsForm.sleep_threshold_minutes"
              :min="1"
              :max="1440"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.minutes')"
            />
          </a-form-item>
          <!-- 以下两项仅作用于手动"进入睡眠"：开启自动休眠时隐藏（值仍随表单保存，不丢失） -->
          <a-form-item
            v-if="!settingsForm.auto_sleep_enabled"
            :label="t('sleep.sleepDurationMinutes')"
            :extra="t('sleep.manualOnlyHint')"
          >
            <a-input-number
              v-model:value="settingsForm.sleep_duration_minutes"
              :min="1"
              :max="1440"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.minutes')"
            />
          </a-form-item>
          <a-form-item
            v-if="!settingsForm.auto_sleep_enabled"
            :label="t('sleep.enableDreaming')"
            :extra="t('sleep.manualOnlyHint')"
          >
            <a-switch v-model:checked="settingsForm.dream_replay_enabled" />
          </a-form-item>
          <a-form-item :label="t('sleep.enableMemoryMerge')">
            <a-switch v-model:checked="settingsForm.memory_consolidation_enabled" />
          </a-form-item>
          <a-form-item :label="t('sleep.enableConflictResolution')">
            <a-switch v-model:checked="settingsForm.conflict_resolution_enabled" />
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

      <!-- Sleep rhythm: 阶段推进参数（判定模式 / 各阶段阈值 / 监控间隔） -->
      <GlassCard :title="t('sleep.phaseParams')" style="margin-top: 16px">
        <a-form layout="vertical" :model="settingsForm">
          <a-form-item :label="t('sleep.sleepMode')">
            <a-select v-model:value="settingsForm.sleep_mode" style="width: 100%">
              <a-select-option value="temperature">{{ t('sleep.modeTemperature') }}</a-select-option>
              <a-select-option value="time">{{ t('sleep.modeTime') }}</a-select-option>
              <a-select-option value="either">{{ t('sleep.modeEither') }}</a-select-option>
            </a-select>
          </a-form-item>
          <template v-if="settingsForm.sleep_mode === 'temperature'">
            <a-form-item :label="`${t('sleep.lightPhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.temp_threshold_light_sleep"
                :min="0"
                :max="100"
                :step="0.5"
                style="width: 100%"
              />
            </a-form-item>
            <a-form-item :label="`${t('sleep.deepPhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.temp_threshold_deep_sleep"
                :min="0"
                :max="100"
                :step="0.5"
                style="width: 100%"
              />
            </a-form-item>
            <a-form-item :label="`${t('sleep.remPhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.temp_threshold_rem"
                :min="0"
                :max="100"
                :step="0.5"
                style="width: 100%"
              />
            </a-form-item>
            <a-form-item :label="`${t('sleep.hibernatePhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.temp_threshold_hibernate"
                :min="0"
                :max="100"
                :step="0.5"
                style="width: 100%"
              />
            </a-form-item>
          </template>
          <template v-else>
            <a-form-item :label="`${t('sleep.lightPhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.idle_threshold_light_sleep"
                :min="1"
                :max="1440"
                :precision="0"
                style="width: 100%"
                :addon-after="t('sleep.minutes')"
              />
            </a-form-item>
            <a-form-item :label="`${t('sleep.deepPhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.idle_threshold_deep_sleep"
                :min="1"
                :max="1440"
                :precision="0"
                style="width: 100%"
                :addon-after="t('sleep.minutes')"
              />
            </a-form-item>
            <a-form-item :label="`${t('sleep.remPhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.idle_threshold_rem"
                :min="1"
                :max="1440"
                :precision="0"
                style="width: 100%"
                :addon-after="t('sleep.minutes')"
              />
            </a-form-item>
            <a-form-item :label="`${t('sleep.hibernatePhase')} · ${t('sleep.threshold')}`">
              <a-input-number
                v-model:value="settingsForm.idle_threshold_hibernate"
                :min="1"
                :max="1440"
                :precision="0"
                style="width: 100%"
                :addon-after="t('sleep.minutes')"
              />
            </a-form-item>
          </template>
          <a-form-item :label="t('sleep.monitorIntervalSeconds')">
            <a-input-number
              v-model:value="settingsForm.monitor_interval_seconds"
              :min="10"
              :max="3600"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.seconds')"
            />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton
            variant="primary"
            size="sm"
            :loading="saveMutation.loading.value"
            @click="handleSave"
          >
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

// --- API-backed settings form（键位与后端 sleep.py::SleepSettings 一致） ---
const settingsForm = reactive<{
  auto_sleep_enabled: boolean
  sleep_threshold_minutes: number
  sleep_duration_minutes: number
  dream_replay_enabled: boolean
  memory_consolidation_enabled: boolean
  conflict_resolution_enabled: boolean
  sleep_mode: 'temperature' | 'time' | 'either'
  temp_threshold_light_sleep: number
  temp_threshold_deep_sleep: number
  temp_threshold_rem: number
  temp_threshold_hibernate: number
  idle_threshold_light_sleep: number
  idle_threshold_deep_sleep: number
  idle_threshold_rem: number
  idle_threshold_hibernate: number
  monitor_interval_seconds: number
}>({
  auto_sleep_enabled: true,
  sleep_threshold_minutes: 30,
  sleep_duration_minutes: 60,
  dream_replay_enabled: true,
  memory_consolidation_enabled: true,
  conflict_resolution_enabled: true,
  sleep_mode: 'temperature',
  temp_threshold_light_sleep: 30,
  temp_threshold_deep_sleep: 25,
  temp_threshold_rem: 20,
  temp_threshold_hibernate: 15,
  idle_threshold_light_sleep: 30,
  idle_threshold_deep_sleep: 60,
  idle_threshold_rem: 90,
  idle_threshold_hibernate: 120,
  monitor_interval_seconds: 60,
})

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
    const settings = sleepApi.unwrapSleep<SleepSettings>(res)
    if (settings && typeof settings === 'object') {
      settingsForm.auto_sleep_enabled = settings.auto_sleep_enabled ?? settingsForm.auto_sleep_enabled
      settingsForm.sleep_threshold_minutes = settings.sleep_threshold_minutes ?? settingsForm.sleep_threshold_minutes
      settingsForm.sleep_duration_minutes = settings.sleep_duration_minutes ?? settingsForm.sleep_duration_minutes
      settingsForm.dream_replay_enabled = settings.dream_replay_enabled ?? settingsForm.dream_replay_enabled
      settingsForm.memory_consolidation_enabled =
        settings.memory_consolidation_enabled ?? settingsForm.memory_consolidation_enabled
      settingsForm.conflict_resolution_enabled =
        settings.conflict_resolution_enabled ?? settingsForm.conflict_resolution_enabled
      settingsForm.sleep_mode = settings.sleep_mode ?? settingsForm.sleep_mode
      settingsForm.temp_threshold_light_sleep =
        settings.temp_threshold_light_sleep ?? settingsForm.temp_threshold_light_sleep
      settingsForm.temp_threshold_deep_sleep =
        settings.temp_threshold_deep_sleep ?? settingsForm.temp_threshold_deep_sleep
      settingsForm.temp_threshold_rem = settings.temp_threshold_rem ?? settingsForm.temp_threshold_rem
      settingsForm.temp_threshold_hibernate =
        settings.temp_threshold_hibernate ?? settingsForm.temp_threshold_hibernate
      settingsForm.idle_threshold_light_sleep =
        settings.idle_threshold_light_sleep ?? settingsForm.idle_threshold_light_sleep
      settingsForm.idle_threshold_deep_sleep =
        settings.idle_threshold_deep_sleep ?? settingsForm.idle_threshold_deep_sleep
      settingsForm.idle_threshold_rem = settings.idle_threshold_rem ?? settingsForm.idle_threshold_rem
      settingsForm.idle_threshold_hibernate =
        settings.idle_threshold_hibernate ?? settingsForm.idle_threshold_hibernate
      settingsForm.monitor_interval_seconds =
        settings.monitor_interval_seconds ?? settingsForm.monitor_interval_seconds
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
  if (
    settingsForm.sleep_threshold_minutes < 1 ||
    settingsForm.sleep_threshold_minutes > 1440 ||
    settingsForm.sleep_duration_minutes < 1 ||
    settingsForm.sleep_duration_minutes > 1440
  ) {
    message.warning(t('sleep.minIntervalValidation'))
    return
  }

  const payload: Partial<SleepSettings> = {
    auto_sleep_enabled: settingsForm.auto_sleep_enabled,
    sleep_threshold_minutes: settingsForm.sleep_threshold_minutes,
    sleep_duration_minutes: settingsForm.sleep_duration_minutes,
    dream_replay_enabled: settingsForm.dream_replay_enabled,
    memory_consolidation_enabled: settingsForm.memory_consolidation_enabled,
    conflict_resolution_enabled: settingsForm.conflict_resolution_enabled,
    sleep_mode: settingsForm.sleep_mode,
    temp_threshold_light_sleep: settingsForm.temp_threshold_light_sleep,
    temp_threshold_deep_sleep: settingsForm.temp_threshold_deep_sleep,
    temp_threshold_rem: settingsForm.temp_threshold_rem,
    temp_threshold_hibernate: settingsForm.temp_threshold_hibernate,
    idle_threshold_light_sleep: settingsForm.idle_threshold_light_sleep,
    idle_threshold_deep_sleep: settingsForm.idle_threshold_deep_sleep,
    idle_threshold_rem: settingsForm.idle_threshold_rem,
    idle_threshold_hibernate: settingsForm.idle_threshold_hibernate,
    monitor_interval_seconds: settingsForm.monitor_interval_seconds,
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
    await sleepApi.resolveConflict(agentId.value, conflictId, resolution)
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
    await sleepApi.resolveConflict(agentId.value, customResolveConflict.value.id, customResolveValue.value)
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
