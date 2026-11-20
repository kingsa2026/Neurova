<template>
  <div class="voice-minutes-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('voiceMinutes.title') }}</h2>
        <p class="page-subtitle">{{ t('voiceMinutes.subtitle') }}</p>
      </div>
    </div>

    <!-- 上传与处理 -->
    <GlassCard :title="t('voiceMinutes.uploadCard')" variant="subtle">
      <div class="upload-row">
        <label class="pick-file">
          <input
            ref="fileInput"
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.webm"
            @change="onFileChange"
          />
          <span class="pick-file-text">{{ pickedName || t('voiceMinutes.pickFile') }}</span>
        </label>
        <GlassButton variant="primary" :loading="submitting" :disabled="!pickedFile" @click="submit">
          {{ t('voiceMinutes.submit') }}
        </GlassButton>
      </div>
      <p class="upload-hint">{{ t('voiceMinutes.uploadHint') }}</p>
    </GlassCard>

    <!-- 结果 -->
    <GlassCard v-if="job" :title="t('voiceMinutes.resultCard')" variant="subtle">
      <div class="result-status">
        <a-tag :color="statusColor">{{ statusLabel }}</a-tag>
        <a-tag v-if="kindLabel" :color="job.kind === 'task' ? 'orange' : 'blue'">{{ kindLabel }}</a-tag>
        <span v-if="job.task_id" class="task-ref">{{ t('voiceMinutes.taskCreated') }}: {{ job.task_title || job.task_id }}</span>
      </div>
      <a-alert v-if="job.status === 'failed'" type="error" show-icon :message="t('voiceMinutes.failed')" :description="job.error" />
      <a-alert v-else-if="job.status !== 'done'" type="info" show-icon :message="t('voiceMinutes.processing')" />
      <template v-else>
        <div class="result-block">
          <div class="block-label">{{ t('voiceMinutes.summary') }}</div>
          <p class="block-text">{{ job.summary || '—' }}</p>
        </div>
        <div class="result-block">
          <div class="block-label">{{ t('voiceMinutes.transcript') }}</div>
          <pre class="block-text transcript">{{ job.transcript || '—' }}</pre>
        </div>
      </template>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { createVoiceMinutes, getVoiceMinutesStatus } from '@/api/modules/asr'

const { t } = useI18n()

const fileInput = ref<HTMLInputElement | null>(null)
const pickedFile = ref<File | null>(null)
const pickedName = ref('')
const submitting = ref(false)
const pollTimer = ref<ReturnType<typeof setTimeout> | null>(null)

const job = ref<Record<string, any> | null>(null)

const statusColor = computed(() => {
  const s = job.value?.status
  if (s === 'done') return 'success'
  if (s === 'failed') return 'error'
  return 'processing'
})

const statusLabel = computed(() => {
  const s = job.value?.status
  if (s === 'done') return t('voiceMinutes.statusDone')
  if (s === 'failed') return t('voiceMinutes.statusFailed')
  if (s === 'running') return t('voiceMinutes.statusRunning')
  return t('voiceMinutes.statusQueued')
})

const kindLabel = computed(() => {
  const k = job.value?.kind
  if (k === 'task') return t('voiceMinutes.kindTask')
  if (k === 'question') return t('voiceMinutes.kindQuestion')
  return ''
})

function onFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  const f = input?.files?.[0] ?? null
  pickedFile.value = f
  pickedName.value = f ? f.name : ''
}

function stopMinutesPolling(): void {
  if (pollTimer.value !== null) {
    clearTimeout(pollTimer.value)
    pollTimer.value = null
  }
}

async function submit(): Promise<void> {
  if (!pickedFile.value || submitting.value) return
  submitting.value = true
  job.value = null
  stopMinutesPolling()
  try {
    const formData = new FormData()
    formData.append('file', pickedFile.value)
    const resp: any = await createVoiceMinutes(formData)
    const data = resp?.data?.data ?? resp?.data ?? {}
    const jobId = String(data.job_id || '')
    if (!data.queued || !jobId) {
      // 有界背压的诚实形态：后端 429 = 队列满（input_gap 证据已落审计）
      message.error(t('voiceMinutes.queueFull'))
      return
    }
    job.value = { status: 'queued' }
    pollJob(jobId)
  } catch (e: any) {
    const status = e?.response?.status
    if (status === 429) {
      message.error(t('voiceMinutes.queueFull'))
    } else {
      message.error(e?.response?.data?.detail || e?.message || t('common.error'))
    }
  } finally {
    submitting.value = false
  }
}

function pollJob(jobId: string, attempt = 0): void {
  const maxAttempts = 120 // 1.5s × 120 = 3min（纪要为秒级重活，超出即超时提示）
  if (attempt >= maxAttempts) {
    message.error(t('voiceMinutes.timeout'))
    return
  }
  pollTimer.value = setTimeout(async () => {
    try {
      const resp: any = await getVoiceMinutesStatus(jobId)
      const data = resp?.data?.data ?? resp?.data ?? {}
      job.value = data
      if (data.status !== 'done' && data.status !== 'failed') {
        pollJob(jobId, attempt + 1)
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || t('common.error'))
    }
  }, 1500)
}

onBeforeUnmount(stopMinutesPolling)
</script>

<style scoped>
.voice-minutes-page {
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

.upload-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.pick-file {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px dashed var(--nr-glass-border);
  border-radius: 8px;
  cursor: pointer;
  color: var(--nr-text-secondary);
  font-size: 13px;
}

.pick-file input[type='file'] {
  display: none;
}

.pick-file-text {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--nr-text-tertiary);
}

.result-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.task-ref {
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.result-block {
  margin-top: 12px;
}

.block-label {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.block-text {
  margin: 0;
  font-size: 13px;
  color: var(--nr-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.transcript {
  font-family: var(--nr-font-mono);
  max-height: 220px;
  overflow: auto;
}
</style>
