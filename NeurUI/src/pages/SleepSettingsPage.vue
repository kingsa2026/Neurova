<template>
  <div class="sleep-settings-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('sleep.settings') }}</h2>
      <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchSettings">{{ t('common.refresh') }}</GlassButton>
    </div>

    <a-spin :spinning="loading">
      <!-- Sleep schedule -->
      <GlassCard :title="t('sleep.status')" style="margin-top: 8px">
        <a-form layout="vertical" :model="schedule">
          <a-form-item label="Enable Auto-Sleep">
            <a-switch v-model:checked="schedule.enabled" />
          </a-form-item>
          <a-form-item label="Sleep Time">
            <a-time-picker v-model:value="schedule.sleep_time" format="HH:mm" style="width: 100%" />
          </a-form-item>
          <a-form-item label="Wake Time">
            <a-time-picker v-model:value="schedule.wake_time" format="HH:mm" style="width: 100%" />
          </a-form-item>
          <a-form-item label="Max Sleep Duration (hours)">
            <a-input-number v-model:value="schedule.max_duration_hours" :min="1" :max="24" style="width: 100%" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSettings">{{ t('common.save') }}</GlassButton>
        </template>
      </GlassCard>

      <!-- Dream parameters -->
      <GlassCard :title="t('sleep.dreams')" style="margin-top: 16px">
        <a-form layout="vertical" :model="dreams">
          <a-form-item label="Enable Dreaming">
            <a-switch v-model:checked="dreams.enabled" />
          </a-form-item>
          <a-form-item label="Dream Frequency">
            <a-select v-model:value="dreams.frequency" style="width: 100%">
              <a-select-option value="every_sleep">Every Sleep</a-select-option>
              <a-select-option value="random">Random</a-select-option>
              <a-select-option value="never">Never</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="Dream Depth">
            <a-slider v-model:value="dreams.depth" :min="1" :max="10" />
          </a-form-item>
          <a-form-item label="Max Dream Topics">
            <a-input-number v-model:value="dreams.max_topics" :min="1" :max="20" style="width: 100%" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSettings">{{ t('common.save') }}</GlassButton>
        </template>
      </GlassCard>

      <!-- Memory merge settings -->
      <GlassCard :title="t('sleep.merges')" style="margin-top: 16px">
        <a-form layout="vertical" :model="memoryMerge">
          <a-form-item label="Enable Memory Merge">
            <a-switch v-model:checked="memoryMerge.enabled" />
          </a-form-item>
          <a-form-item label="Merge Strategy">
            <a-select v-model:value="memoryMerge.strategy" style="width: 100%">
              <a-select-option value="conservative">Conservative</a-select-option>
              <a-select-option value="balanced">Balanced</a-select-option>
              <a-select-option value="aggressive">Aggressive</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="Conflict Resolution">
            <a-select v-model:value="memoryMerge.conflict_resolution" style="width: 100%">
              <a-select-option value="keep_newest">Keep Newest</a-select-option>
              <a-select-option value="keep_strongest">Keep Strongest</a-select-option>
              <a-select-option value="merge">Merge</a-select-option>
              <a-select-option value="flag">Flag for Review</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="Similarity Threshold">
            <a-slider v-model:value="memoryMerge.similarity_threshold" :min="0" :max="100" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSettings">{{ t('common.save') }}</GlassButton>
        </template>
      </GlassCard>
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
const saving = ref(false)

const schedule = ref({ enabled: true, sleep_time: null as any, wake_time: null as any, max_duration_hours: 8 })
const dreams = ref({ enabled: true, frequency: 'random', depth: 5, max_topics: 5 })
const memoryMerge = ref({ enabled: true, strategy: 'balanced', conflict_resolution: 'keep_newest', similarity_threshold: 70 })

const fetchSettings = async () => {
  loading.value = true
  try {
    const res: any = await request.get(`/sleep/${agentId}/settings`)
    const data = res?.data ?? res ?? {}
    if (data.schedule) schedule.value = { ...schedule.value, ...data.schedule }
    if (data.dreams) dreams.value = { ...dreams.value, ...data.dreams }
    if (data.memory_merge) memoryMerge.value = { ...memoryMerge.value, ...data.memory_merge }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const saveSettings = async () => {
  saving.value = true
  try {
    await request.put(`/sleep/${agentId}/settings`, {
      schedule: schedule.value,
      dreams: dreams.value,
      memory_merge: memoryMerge.value,
    })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

onMounted(fetchSettings)
</script>

<style scoped>
.sleep-settings-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
</style>
