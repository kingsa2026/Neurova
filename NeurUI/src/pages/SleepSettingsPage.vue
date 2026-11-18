<template>
  <div class="sleep-settings-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('sleep.settings') }}</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchSettings">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <AgentPageTabs :tabs="sleepTabs" />

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
          <a-divider style="margin: 8px 0">{{ t('sleep.phaseMaxSection') }}</a-divider>
          <a-form-item :label="`${t('sleep.lightPhase')} · ${t('sleep.phaseMax')}`">
            <a-input-number
              v-model:value="settingsForm.phase_max_minutes_light_sleep"
              :min="0"
              :max="1440"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.minutes')"
            />
          </a-form-item>
          <a-form-item :label="`${t('sleep.remPhase')} · ${t('sleep.phaseMax')}`">
            <a-input-number
              v-model:value="settingsForm.phase_max_minutes_rem"
              :min="0"
              :max="1440"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.minutes')"
            />
          </a-form-item>
          <a-form-item :label="`${t('sleep.deepPhase')} · ${t('sleep.phaseMax')}`">
            <a-input-number
              v-model:value="settingsForm.phase_max_minutes_deep_sleep"
              :min="0"
              :max="1440"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.minutes')"
            />
          </a-form-item>
          <a-form-item :label="`${t('sleep.hibernatePhase')} · ${t('sleep.phaseMax')}`">
            <a-input-number
              v-model:value="settingsForm.phase_max_minutes_hibernate"
              :min="0"
              :max="1440"
              :precision="0"
              style="width: 100%"
              :addon-after="t('sleep.minutes')"
            />
            <template #extra>{{ t('sleep.phaseMaxHint') }}</template>
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
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import AgentPageTabs from '@/components/AgentPageTabs.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useMutation } from '@/composables/useAPI'
import * as sleepApi from '@/api/modules/sleep'
import type { SleepSettings } from '@/api/modules/sleep'

const { t } = useI18n()
const { agentId } = useAgentPage({
  onAgentChange: () => {
    fetchSettings()
  },
})

const sleepTabs = computed(() => [
  { labelKey: 'nav.sleepstatus', to: `/agent/${agentId.value}/sleep/status` },
  { labelKey: 'nav.sleepsettings', to: `/agent/${agentId.value}/sleep/settings` },
])

// --- State ---
const loading = ref(false)

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
  phase_max_minutes_light_sleep: number
  phase_max_minutes_deep_sleep: number
  phase_max_minutes_rem: number
  phase_max_minutes_hibernate: number
}>({
  auto_sleep_enabled: true,
  sleep_threshold_minutes: 30,
  sleep_duration_minutes: 60,
  dream_replay_enabled: true,
  memory_consolidation_enabled: true,
  conflict_resolution_enabled: true,
  sleep_mode: 'temperature',
  temp_threshold_light_sleep: 30,
  temp_threshold_rem: 25,
  temp_threshold_deep_sleep: 20,
  temp_threshold_hibernate: 15,
  idle_threshold_light_sleep: 30,
  idle_threshold_rem: 60,
  idle_threshold_deep_sleep: 90,
  idle_threshold_hibernate: 120,
  monitor_interval_seconds: 60,
  phase_max_minutes_light_sleep: 120,
  phase_max_minutes_rem: 60,
  phase_max_minutes_deep_sleep: 180,
  phase_max_minutes_hibernate: 120,
})

// --- Mutation for save ---
const saveMutation = useMutation<Partial<SleepSettings>, SleepSettings>(
  (data) => sleepApi.updateSleepSettings(agentId.value, data),
)

// --- Helpers ---

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
      settingsForm.phase_max_minutes_light_sleep =
        settings.phase_max_minutes_light_sleep ?? settingsForm.phase_max_minutes_light_sleep
      settingsForm.phase_max_minutes_deep_sleep =
        settings.phase_max_minutes_deep_sleep ?? settingsForm.phase_max_minutes_deep_sleep
      settingsForm.phase_max_minutes_rem =
        settings.phase_max_minutes_rem ?? settingsForm.phase_max_minutes_rem
      settingsForm.phase_max_minutes_hibernate =
        settings.phase_max_minutes_hibernate ?? settingsForm.phase_max_minutes_hibernate
    }
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
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
    phase_max_minutes_light_sleep: settingsForm.phase_max_minutes_light_sleep,
    phase_max_minutes_deep_sleep: settingsForm.phase_max_minutes_deep_sleep,
    phase_max_minutes_rem: settingsForm.phase_max_minutes_rem,
    phase_max_minutes_hibernate: settingsForm.phase_max_minutes_hibernate,
  }

  const result = await saveMutation.execute(payload)
  if (result) {
    message.success(t('common.success'))
    await fetchSettings()
  } else if (saveMutation.error.value) {
    message.error(saveMutation.error.value)
  }
}

onMounted(() => {
  fetchSettings()
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
</style>
