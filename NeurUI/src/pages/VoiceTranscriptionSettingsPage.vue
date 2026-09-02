<template>
  <div class="voice-transcription-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('voiceTranscription.title') }}</h2>
        <p class="page-subtitle">{{ t('voiceTranscription.subtitle') }}</p>
      </div>
      <GlassButton variant="secondary" :loading="loading" @click="fetchAll">
        {{ t('common.refresh') }}
      </GlassButton>
    </div>

    <!-- 当前生效引擎 -->
    <GlassCard :title="t('voiceTranscription.currentEngine')" variant="subtle">
      <div class="engine-status">
        <a-tag :color="activeEngineColor">{{ activeEngineLabel }}</a-tag>
        <span class="engine-chain">{{ t('voiceTranscription.chain') }}: funasr → remote_whisper → whisper</span>
      </div>
    </GlassCard>

    <!-- 双模配置 -->
    <GlassCard :title="t('voiceTranscription.dualMode')" variant="subtle">
      <div class="mode-grid">
        <!-- 远程 Whisper -->
        <div class="mode-card">
          <div class="mode-header">
            <span class="mode-name">Whisper (Remote)</span>
            <a-tag color="cyan">API</a-tag>
          </div>
          <p class="mode-desc">{{ t('voiceTranscription.remoteDesc') }}</p>
          <div class="mode-field">
            <span class="field-label">Base URL</span>
            <a-input v-model:value="remoteForm.baseUrl" :placeholder="'https://api.openai.com/v1'" size="small" />
          </div>
          <div class="mode-field">
            <span class="field-label">API Key</span>
            <a-input-password v-model:value="remoteForm.apiKey" :placeholder="t('voiceTranscription.keyPlaceholder')" size="small" />
          </div>
          <div class="mode-field">
            <span class="field-label">Model</span>
            <a-input v-model:value="remoteForm.model" placeholder="whisper-1" size="small" />
          </div>
        </div>

        <!-- 本地 Whisper（opt-in） -->
        <div class="mode-card">
          <div class="mode-header">
            <span class="mode-name">Whisper (Local)</span>
            <a-tag :color="whisperStatus.model_ready ? 'success' : 'default'">
              {{ whisperStatus.model_ready ? t('voiceTranscription.ready') : t('voiceTranscription.notDownloaded') }}
            </a-tag>
          </div>
          <p class="mode-desc">{{ t('voiceTranscription.localDesc') }}</p>
          <div class="consent-box">
            <a-alert
              v-if="!whisperStatus.consent"
              type="warning"
              show-icon
              :message="t('voiceTranscription.consentTitle')"
              :description="t('voiceTranscription.consentDesc')"
            />
            <a-button
              v-if="!whisperStatus.consent"
              type="primary"
              danger
              :loading="consentLoading"
              @click="grantConsent"
            >
              {{ t('voiceTranscription.consentButton') }}
            </a-button>
            <a-alert
              v-else
              type="success"
              show-icon
              :message="t('voiceTranscription.consentGranted')"
              :description="t('voiceTranscription.consentGrantedDesc')"
            />
          </div>
        </div>
      </div>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { request } from '@/api'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()

const loading = ref(false)
const consentLoading = ref(false)
const isAdmin = computed(() => authStore.currentUser?.role === 'admin')

const whisperStatus = reactive({
  consent: false,
  model_ready: false,
  model_dir: '',
  active_engine: '' as string | null,
  chain: [] as string[],
})

const remoteForm = reactive({
  baseUrl: '',
  apiKey: '',
  model: 'whisper-1',
})

const activeEngineLabel = computed(() => {
  const eng = whisperStatus.active_engine
  if (!eng) return t('voiceTranscription.noEngine')
  if (eng === 'funasr') return 'FunASR Paraformer'
  if (eng === 'remote_whisper') return 'Whisper (Remote)'
  if (eng === 'whisper') return 'Whisper (Local)'
  return eng
})

const activeEngineColor = computed(() =>
  whisperStatus.active_engine ? 'success' : 'default',
)

const fetchAll = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/audio/asr/local-whisper/status')
    const data = res?.data?.data ?? res?.data ?? {}
    Object.assign(whisperStatus, {
      consent: !!data.consent,
      model_ready: !!data.model_ready,
      model_dir: data.model_dir ?? '',
      active_engine: data.active_engine ?? null,
      chain: data.chain ?? [],
    })
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const grantConsent = async () => {
  consentLoading.value = true
  try {
    // 同意后服务端阻塞下载+重跑链（可能数分钟）——前端放宽超时
    const res: any = await request.post(
      '/audio/asr/local-whisper/consent',
      {},
      { timeout: 660_000 },
    )
    const data = res?.data?.data ?? res?.data ?? {}
    Object.assign(whisperStatus, {
      consent: !!data.status?.consent,
      model_ready: !!data.status?.model_ready,
      active_engine: data.status?.active_engine ?? null,
    })
    message.success(t('voiceTranscription.consentGranted'))
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    consentLoading.value = false
  }
}

onMounted(() => {
  if (isAdmin.value) fetchAll()
})
</script>

<style scoped>
.voice-transcription-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
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

.engine-status {
  display: flex;
  align-items: center;
  gap: 12px;
}

.engine-chain {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  font-family: var(--nr-font-mono);
}

.mode-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}

.mode-card {
  padding: 16px;
  border-radius: 10px;
  border: 1px solid var(--nr-glass-border);
  background: rgba(255, 255, 255, 0.03);
}

.mode-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.mode-name {
  font-weight: 600;
  color: var(--nr-text-primary);
}

.mode-desc {
  font-size: 12px;
  color: var(--nr-text-secondary);
  margin: 0 0 12px;
}

.mode-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}

.field-label {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.consent-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}
</style>
