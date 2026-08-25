<template>
  <div class="memory-settings-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('memorySettings.title') }}</h2>
        <p class="page-subtitle">{{ t('memorySettings.subtitle') }}</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchSchema">
          {{ t('common.refresh') }}
        </GlassButton>
        <a-dropdown>
          <GlassButton variant="secondary" size="sm">
            {{ t('memorySettings.reset') }} ▾
          </GlassButton>
          <template #overlay>
            <a-menu>
              <a-menu-item @click="confirmResetAll">
                {{ t('memorySettings.resetAll') }}
              </a-menu-item>
              <a-menu-item v-if="selectedKeys.length" @click="confirmResetSelected">
                {{ t('memorySettings.resetSelected') }} ({{ selectedKeys.length }})
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <GlassButton variant="secondary" size="sm" @click="handleExport">
          {{ t('memorySettings.export') }}
        </GlassButton>
        <a-upload :before-upload="handleImport" :show-upload-list="false" accept=".json">
          <GlassButton variant="secondary" size="sm">
            {{ t('memorySettings.import') }}
          </GlassButton>
        </a-upload>
      </div>
    </div>

    <a-spin :spinning="loading">
      <!-- Section navigation -->
      <GlassCard style="margin-top: 8px">
        <div class="section-nav">
          <a-radio-group v-model:value="activeSection" button-style="solid" size="small">
            <a-radio-button value="__all__">{{ t('memorySettings.allSettings') }}</a-radio-button>
            <a-radio-button v-for="sec in sections" :key="sec" :value="sec">
              {{ sectionLabel(sec) }}
            </a-radio-button>
          </a-radio-group>
        </div>
      </GlassCard>

      <!-- Parameter sections -->
      <template v-if="schema.length > 0">
        <template v-for="sec in visibleSections" :key="sec">
          <GlassCard :title="sectionLabel(sec)" style="margin-top: 16px">
            <template #extra>
              <span class="section-desc">{{ sectionDesc(sec) }}</span>
            </template>

            <div class="param-list">
              <div
                v-for="param in paramsInSection(sec)"
                :key="param.key"
                class="param-row"
                :class="{ selected: selectedKeys.includes(param.key) }"
              >
                <div class="param-select">
                  <a-checkbox
                    :checked="selectedKeys.includes(param.key)"
                    @change="(e: any) => toggleSelect(param.key, e.target.checked)"
                  />
                </div>

                <div class="param-info">
                  <div class="param-name">{{ formatParamKey(param.key) }}</div>
                  <div class="param-desc">{{ param.description }}</div>
                  <div class="param-meta">
                    <a-tag size="small" :color="typeColor(param.type)">{{ param.type }}</a-tag>
                    <span v-if="param.min != null || param.max != null" class="param-range">
                      {{ param.min ?? '∞' }} ~ {{ param.max ?? '∞' }}
                    </span>
                    <span class="param-default">
                      {{ t('memorySettings.defaultValue') }}: <code>{{ param.default }}</code>
                    </span>
                  </div>
                </div>

                <div class="param-control">
                  <!-- Float → Slider + number input -->
                  <template v-if="param.type === 'float'">
                    <div class="slider-row">
                      <a-slider
                        :value="currentValues[param.key] as number"
                        :min="param.min ?? 0"
                        :max="param.max ?? 1"
                        :step="sliderStep(param)"
                        style="flex: 1"
                        @change="(v: number) => setValue(param.key, v)"
                      />
                      <a-input-number
                        :value="currentValues[param.key] as number"
                        :min="param.min ?? 0"
                        :max="param.max ?? 1"
                        :step="sliderStep(param)"
                        size="small"
                        style="width: 90px; margin-left: 8px"
                        @change="(v: number | null) => setValue(param.key, v ?? param.default)"
                      />
                    </div>
                  </template>

                  <!-- Int → Input number -->
                  <template v-else-if="param.type === 'int'">
                    <a-input-number
                      :value="currentValues[param.key] as number"
                      :min="param.min ?? undefined"
                      :max="param.max ?? undefined"
                      :step="1"
                      style="width: 160px"
                      @change="(v: number | null) => setValue(param.key, v ?? param.default)"
                    />
                  </template>

                  <!-- Bool → Switch -->
                  <template v-else-if="param.type === 'bool'">
                    <a-switch
                      :checked="!!currentValues[param.key]"
                      @change="(v: boolean) => setValue(param.key, v)"
                    />
                  </template>

                  <!-- Fallback -->
                  <template v-else>
                    <a-input
                      :value="String(currentValues[param.key] ?? '')"
                      style="width: 200px"
                      @change="(e: any) => setValue(param.key, e.target.value)"
                    />
                  </template>
                </div>

                <div class="param-changed" v-if="isChanged(param.key)">
                  <a-tag color="orange">{{ t('memorySettings.modified') }}</a-tag>
                </div>
              </div>
            </div>
          </GlassCard>
        </template>
      </template>

      <!-- Empty state -->
      <a-empty v-if="!loading && schema.length === 0" :description="t('memorySettings.noSchema')" />
    </a-spin>

    <!-- Save bar -->
    <div v-if="hasChanges" class="save-bar">
      <div class="save-info">
        {{ changedKeys.length }} {{ t('memorySettings.paramKey') }} changed
      </div>
      <GlassButton variant="ghost" size="sm" @click="discardChanges">
        {{ t('common.cancel') }}
      </GlassButton>
      <GlassButton variant="primary" size="sm" :loading="saving" @click="handleSave">
        {{ t('memorySettings.save') }}
      </GlassButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import * as memSettingsApi from '@/api/modules/memory-settings'
import type { ParamSchema } from '@/api/modules/memory-settings'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const schema = ref<ParamSchema[]>([])
const currentValues = ref<Record<string, any>>({})
const baselineValues = ref<Record<string, any>>({})
const activeSection = ref('__all__')
const selectedKeys = ref<string[]>([])

// --- Derived ---

const sections = computed(() => {
  const set = new Set<string>()
  for (const p of schema.value) {
    const sec = p.key.split('.')[0]
    if (sec) set.add(sec)
  }
  return Array.from(set)
})

const visibleSections = computed(() =>
  activeSection.value === '__all__' ? sections.value : [activeSection.value]
)

const changedKeys = computed(() => {
  const keys: string[] = []
  for (const p of schema.value) {
    if (isChanged(p.key)) keys.push(p.key)
  }
  return keys
})

const hasChanges = computed(() => changedKeys.value.length > 0)

// --- Helpers ---

const sectionLabelMap: Record<string, string> = {
  temperature: 'memorySettings.sectionTemperature',
  auto_context: 'memorySettings.sectionAutoContext',
  compression: 'memorySettings.sectionCompression',
  activation: 'memorySettings.sectionActivation',
  threshold: 'memorySettings.sectionThreshold',
  graph: 'memorySettings.sectionGraph',
  vector_search: 'memorySettings.sectionVectorSearch',
  manager: 'memorySettings.sectionManager',
}

const sectionDescMap: Record<string, string> = {
  temperature: 'memorySettings.sectionTemperatureDesc',
  auto_context: 'memorySettings.sectionAutoContextDesc',
  compression: 'memorySettings.sectionCompressionDesc',
  activation: 'memorySettings.sectionActivationDesc',
  threshold: 'memorySettings.sectionThresholdDesc',
  graph: 'memorySettings.sectionGraphDesc',
  vector_search: 'memorySettings.sectionVectorSearchDesc',
  manager: 'memorySettings.sectionManagerDesc',
}

const sectionLabel = (sec: string) => {
  const key = sectionLabelMap[sec]
  return key ? t(key) : sec
}

const sectionDesc = (sec: string) => {
  const key = sectionDescMap[sec]
  return key ? t(key) : ''
}

const paramsInSection = (sec: string) => schema.value.filter(p => p.key.startsWith(sec + '.'))

const formatParamKey = (key: string) => {
  const parts = key.split('.')
  return parts.length > 1 ? parts.slice(1).join('.') : key
}

const typeColor = (type: string) => {
  if (type === 'float') return 'blue'
  if (type === 'int') return 'green'
  if (type === 'bool') return 'purple'
  return 'default'
}

const sliderStep = (param: ParamSchema) => {
  const range = (param.max ?? 1) - (param.min ?? 0)
  if (range <= 1) return 0.01
  if (range <= 10) return 0.1
  if (range <= 100) return 1
  return Math.max(1, Math.round(range / 100))
}

const isChanged = (key: string) => {
  return JSON.stringify(currentValues.value[key]) !== JSON.stringify(baselineValues.value[key])
}

const setValue = (key: string, value: any) => {
  currentValues.value = { ...currentValues.value, [key]: value }
}

const toggleSelect = (key: string, checked: boolean) => {
  if (checked) {
    if (!selectedKeys.value.includes(key)) selectedKeys.value = [...selectedKeys.value, key]
  } else {
    selectedKeys.value = selectedKeys.value.filter(k => k !== key)
  }
}

// --- Data operations ---

const fetchSchema = async () => {
  loading.value = true
  try {
    const res = await memSettingsApi.getSchema()
    const list: ParamSchema[] = Array.isArray(res) ? res : (res as any)?.data ?? []
    schema.value = list

    // Initialize current + baseline values from schema
    const vals: Record<string, any> = {}
    for (const p of list) {
      vals[p.key] = p.current ?? p.default
    }
    currentValues.value = { ...vals }
    baselineValues.value = { ...vals }
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('memorySettings.noSchema'))
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  if (!changedKeys.value.length) return
  saving.value = true
  try {
    const updates: Record<string, any> = {}
    for (const key of changedKeys.value) {
      updates[key] = currentValues.value[key]
    }
    await memSettingsApi.updateSettings(updates)
    message.success(t('memorySettings.saved'))

    // Refresh schema to get updated current values
    await fetchSchema()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    saving.value = false
  }
}

const discardChanges = () => {
  currentValues.value = { ...baselineValues.value }
}

const confirmResetAll = () => {
  Modal.confirm({
    title: t('memorySettings.resetAll'),
    content: t('memorySettings.resetAllConfirm'),
    onOk: () => doReset(null),
  })
}

const confirmResetSelected = () => {
  if (!selectedKeys.value.length) return
  Modal.confirm({
    title: t('memorySettings.resetSelected'),
    content: t('memorySettings.resetConfirm'),
    onOk: () => doReset(selectedKeys.value),
  })
}

const doReset = async (keys: string[] | null) => {
  saving.value = true
  try {
    await memSettingsApi.resetSettings(keys)
    message.success(t('memorySettings.resetDone'))
    selectedKeys.value = []
    await fetchSchema()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    saving.value = false
  }
}

const handleExport = async () => {
  try {
    const res = await memSettingsApi.exportSettings()
    const data = (res as any)?.data ?? res
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `memory-settings-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('memorySettings.exportSuccess'))
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  }
}

const handleImport = (file: File) => {
  const reader = new FileReader()
  reader.onload = async () => {
    try {
      const settings = JSON.parse(reader.result as string)
      await memSettingsApi.importSettings(settings)
      message.success(t('memorySettings.importSuccess'))
      await fetchSchema()
    } catch (e: any) {
      message.error(e?.response?.data?.message || e?.message || t('common.error'))
    }
  }
  reader.readAsText(file)
  return false // prevent auto upload
}

onMounted(() => {
  fetchSchema()
})
</script>

<style scoped>
.memory-settings-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 80px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary);
  font-size: 13px;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.section-nav {
  overflow-x: auto;
}

.section-desc {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  font-style: italic;
}

/* Parameter rows */
.param-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.param-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 8px;
  border-radius: 8px;
  transition: background 0.15s;
}

.param-row:hover {
  background: rgba(255, 255, 255, 0.03);
}

.param-row.selected {
  background: rgba(99, 102, 241, 0.08);
}

.param-select {
  flex-shrink: 0;
}

.param-info {
  flex: 1;
  min-width: 0;
}

.param-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
  font-family: var(--nr-font-mono);
}

.param-desc {
  font-size: 12px;
  color: var(--nr-text-secondary);
  margin-top: 2px;
  line-height: 1.4;
}

.param-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.param-range {
  font-size: 11px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-tertiary);
}

.param-default {
  font-size: 11px;
  color: var(--nr-text-tertiary);
}

.param-default code {
  font-family: var(--nr-font-mono);
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 4px;
  border-radius: 3px;
}

.param-control {
  flex-shrink: 0;
  min-width: 180px;
  display: flex;
  justify-content: flex-end;
}

.slider-row {
  display: flex;
  align-items: center;
  min-width: 240px;
}

.param-changed {
  flex-shrink: 0;
}

/* Save bar (sticky bottom) */
.save-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 24px;
  background: var(--nr-bg-primary, #1a1a2e);
  border-top: 1px solid var(--nr-glass-border, rgba(255, 255, 255, 0.1));
  z-index: 100;
}

.save-info {
  font-size: 13px;
  color: var(--nr-text-secondary);
  margin-right: auto;
}
</style>
