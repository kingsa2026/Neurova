<template>
  <div class="setting-page">
    <h2 class="page-title">{{ t('system.settings') }}</h2>

    <a-tabs v-model:activeKey="activeTab" tab-position="left" class="settings-tabs">
      <!-- General -->
      <a-tab-pane key="general" :tab="t('common.type') === 'Type' ? 'General' : t('common.type')">
        <GlassCard title="General Settings">
          <a-form layout="vertical" :model="general">
            <a-form-item label="App Name">
              <a-input v-model:value="general.app_name" />
            </a-form-item>
            <a-form-item :label="t('theme.language')">
              <a-select v-model:value="general.language" style="width: 100%">
                <a-select-option v-for="loc in supportedLocales" :key="loc.code" :value="loc.code">
                  {{ loc.flag }} {{ loc.name }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item :label="t('theme.appearance')">
              <a-switch v-model:checked="isDark" :checked-children="t('theme.dark')" :un-checked-children="t('theme.light')" @change="onThemeToggle" />
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('general')">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- LLM -->
      <a-tab-pane key="llm" tab="LLM">
        <GlassCard title="LLM Settings">
          <a-form layout="vertical" :model="llm">
            <a-form-item :label="t('model.providers')">
              <a-select v-model:value="llm.default_provider" style="width: 100%">
                <a-select-option v-for="p in providerOptions" :key="p" :value="p">{{ p }}</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item :label="t('model.active')">
              <a-input v-model:value="llm.default_model" />
            </a-form-item>
            <a-form-item :label="t('agent.temperature')">
              <a-slider v-model:value="llm.temperature" :min="0" :max="2" :step="0.1" />
            </a-form-item>
            <a-form-item :label="t('agent.maxTokens')">
              <a-input-number v-model:value="llm.max_tokens" :min="1" :max="128000" style="width: 100%" />
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('llm')">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- Security -->
      <a-tab-pane key="security" tab="Security">
        <GlassCard title="Security Settings">
          <a-form layout="vertical" :model="security">
            <a-form-item label="JWT Secret">
              <a-input-password v-model:value="security.jwt_secret" />
            </a-form-item>
            <a-form-item label="JWT Expiry (hours)">
              <a-input-number v-model:value="security.jwt_expiry_hours" :min="1" :max="8760" style="width: 100%" />
            </a-form-item>
            <a-form-item label="Min Password Length">
              <a-input-number v-model:value="security.min_password_length" :min="6" :max="64" style="width: 100%" />
            </a-form-item>
            <a-form-item label="Require Special Characters">
              <a-switch v-model:checked="security.require_special" />
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('security')">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- Storage -->
      <a-tab-pane key="storage" tab="Storage">
        <GlassCard title="Storage Settings">
          <a-form layout="vertical" :model="storage">
            <a-form-item label="Media Storage Path">
              <a-input v-model:value="storage.media_path" />
            </a-form-item>
            <a-form-item label="Max Upload Size (MB)">
              <a-input-number v-model:value="storage.max_upload_mb" :min="1" :max="1024" style="width: 100%" />
            </a-form-item>
            <a-form-item label="Cache TTL (minutes)">
              <a-input-number v-model:value="storage.cache_ttl_minutes" :min="1" style="width: 100%" />
            </a-form-item>
          </a-form>
          <template #footer>
            <div class="storage-actions">
              <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('storage')">{{ t('common.save') }}</GlassButton>
              <GlassButton variant="danger" size="sm" :loading="clearingCache" @click="clearCache">{{ t('common.refresh') }} Cache</GlassButton>
            </div>
          </template>
        </GlassCard>
      </a-tab-pane>

      <!-- Advanced -->
      <a-tab-pane key="advanced" tab="Advanced">
        <GlassCard title="Advanced Settings">
          <a-form layout="vertical" :model="advanced">
            <a-form-item label="Debug Mode">
              <a-switch v-model:checked="advanced.debug_mode" />
            </a-form-item>
            <a-form-item label="Log Level">
              <a-select v-model:value="advanced.log_level" style="width: 100%">
                <a-select-option value="debug">Debug</a-select-option>
                <a-select-option value="info">Info</a-select-option>
                <a-select-option value="warning">Warning</a-select-option>
                <a-select-option value="error">Error</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="Enable Telemetry">
              <a-switch v-model:checked="advanced.telemetry" />
            </a-form-item>
          </a-form>
          <template #footer>
            <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSection('advanced')">{{ t('common.save') }}</GlassButton>
          </template>
        </GlassCard>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import { useAppStore } from '@/stores/app'
import { supportedLocales } from '@/i18n'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t, locale } = useI18n()
const appStore = useAppStore()

const activeTab = ref('general')
const saving = ref(false)
const clearingCache = ref(false)
const isDark = ref(appStore.isDark)
const providerOptions = ref<string[]>([])

const general = ref({ app_name: 'Neurova', language: locale.value })
const llm = ref({ default_provider: '', default_model: '', temperature: 0.7, max_tokens: 4096 })
const security = ref({ jwt_secret: '', jwt_expiry_hours: 24, min_password_length: 8, require_special: true })
const storage = ref({ media_path: '/data/media', max_upload_mb: 50, cache_ttl_minutes: 60 })
const advanced = ref({ debug_mode: false, log_level: 'info', telemetry: false })

const onThemeToggle = () => {
  appStore.toggleTheme()
  isDark.value = appStore.isDark
}

const fetchSettings = async () => {
  try {
    const res: any = await request.get('/settings')
    const data = res?.data ?? res ?? {}
    if (data.general) general.value = { ...general.value, ...data.general }
    if (data.llm) llm.value = { ...llm.value, ...data.llm }
    if (data.security) security.value = { ...security.value, ...data.security }
    if (data.storage) storage.value = { ...storage.value, ...data.storage }
    if (data.advanced) advanced.value = { ...advanced.value, ...data.advanced }
    if (data.providers) providerOptions.value = data.providers
  } catch {
    message.error(t('common.error'))
  }
}

const saveSection = async (section: string) => {
  saving.value = true
  try {
    const sectionMap: Record<string, any> = { general: general.value, llm: llm.value, security: security.value, storage: storage.value, advanced: advanced.value }
    await request.put('/settings', { section, data: sectionMap[section] })

    if (section === 'general' && general.value.language !== locale.value) {
      locale.value = general.value.language
      appStore.setLocale(general.value.language)
    }

    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const clearCache = async () => {
  clearingCache.value = true
  try {
    await request.post('/settings/clear-cache')
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    clearingCache.value = false
  }
}

onMounted(fetchSettings)
</script>

<style scoped>
.setting-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.settings-tabs { min-height: 400px; }
:deep(.settings-tabs .ant-tabs-tab) { padding: 10px 16px !important; color: var(--nr-text-secondary) !important; }
:deep(.settings-tabs .ant-tabs-tab-active .ant-tabs-tab-btn) { color: var(--nr-text-primary) !important; }
.storage-actions { display: flex; gap: 8px; }
</style>
