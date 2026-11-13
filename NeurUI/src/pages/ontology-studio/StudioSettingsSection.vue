<template>
  <div class="settings-section" data-testid="studio-settings">
    <GlassCard class="setting-card">
      <div class="setting-row">
        <div class="setting-text">
          <h4 class="setting-title">{{ t('ontology.settingsExtractTitle') }}</h4>
          <p class="setting-desc">{{ t('ontology.settingsExtractDesc') }}</p>
          <p class="setting-source mono" data-testid="settings-source">
            {{ t('ontology.settingsSource') }}: {{ sourceLabel }}
          </p>
        </div>
        <a-switch :checked="extractOnUpdate" :disabled="!isAdmin || saving"
                  data-testid="settings-extract-toggle"
                  @change="(v: boolean) => updateExtract(v)" />
      </div>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import { getOntologySettings, updateOntologySettings } from '@/api/modules/ontology'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.currentUser?.role === 'admin')

const extractOnUpdate = ref(false)
const source = ref<'env' | 'setting' | 'default'>('default')
const saving = ref(false)

const sourceLabel = computed(() => {
  if (source.value === 'env') return t('ontology.settingsSourceEnv')
  if (source.value === 'setting') return t('ontology.settingsSourceSetting')
  return t('ontology.settingsSourceDefault')
})

async function loadSettings() {
  try {
    const res: any = await getOntologySettings()
    const data = res?.data ?? {}
    extractOnUpdate.value = Boolean(data.extract_on_update)
    source.value = data.source ?? 'default'
  } catch {
    /* 读数失败保持默认，不打断页面 */
  }
}

async function updateExtract(v: boolean) {
  saving.value = true
  try {
    await updateOntologySettings(v)
    extractOnUpdate.value = v
    source.value = 'setting'
    message.success(t('ontology.settingsSaved'))
  } catch (err: any) {
    message.error(err?.response?.data?.detail || t('common.error'))
    await loadSettings()
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--nr-space-md);
}

.setting-title {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 600;
}

.setting-desc {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--nr-text-secondary, rgba(128, 128, 128, 0.7));
  max-width: 560px;
}

.setting-source {
  margin: 0;
  font-size: 11px;
  color: var(--nr-text-tertiary, rgba(128, 128, 128, 0.45));
}

.mono {
  font-family: var(--nr-font-mono, monospace);
}
</style>
