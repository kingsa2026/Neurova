<script setup lang="ts">
/**
 * AIGC 音乐生成页（M1/L5 多模态追平）：fal Queue API 异步任务，两段式与
 * VideoGenPage 同范式——提交 POST /generation/music 拿 task_id → 轮询
 * GET /generation/music/status/{task_id}（四态 submitted/running/succeeded/failed）→
 * 终态展示音频播放器/下载（产物 URL 与音频页同形态：本地产物 + withFileToken）。
 * 模型下拉走 useAigcModels 的 music_generation 能力过滤；后端暂无音乐模型卡时
 * 诚实提示「无预置音乐模型」，仅保留 auto（提交由后端按能力路由到默认 fal 模型），
 * 不硬编码假模型列表。未决任务轮询卸载清理（BUG-24 同款纪律）。
 */
import { onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { submitMusic, getMusicTaskStatus, type MusicGenerationPayload } from '@/api/modules/generation'
import { useAigcModels } from '@/composables/useAigcModels'
import { withFileToken } from '@/utils/genFiles'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import AigcHistoryList from '@/components/aigc/AigcHistoryList.vue'

const { t } = useI18n()
const { musicModelOptions } = useAigcModels()

const prompt = ref('')
const model = ref('auto')
const duration = ref(30)
const generating = ref(false)
const status = ref<{ status: string; progress: number; url?: string; error?: string } | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function generate() {
  if (!prompt.value.trim()) return
  generating.value = true
  status.value = { status: 'submitted', progress: 0 }
  try {
    // 协议/服务商不随请求下发：服务端 derive_generation_protocol 按
    // 模型→服务商 base_url 自适应推导（与视频页同口径）
    const payload: MusicGenerationPayload = {
      prompt: prompt.value,
      model: model.value === 'auto' ? undefined : model.value,
      duration: duration.value,
    }
    const res: any = await submitMusic(payload)
    const data = res?.data ?? res
    const taskId = data?.task_id ?? data?.id
    if (!taskId) {
      generating.value = false
      message.error(res?.message || t('aigc.generateError'))
      return
    }
    status.value = { status: data?.status ?? 'running', progress: 5 }
    pollStatus(taskId)
  } catch {
    message.error(t('aigc.generateError'))
    generating.value = false
  }
}

function pollStatus(taskId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const res: any = await getMusicTaskStatus(taskId)
      const data = res?.data ?? res
      status.value = {
        status: data?.status ?? 'running',
        progress: data?.status === 'succeeded' ? 100 : status.value?.progress ?? 0,
        url: data?.url,
        error: data?.error,
      }
      if (data?.status === 'succeeded' || data?.status === 'failed') {
        clearInterval(pollTimer!)
        pollTimer = null
        generating.value = false
        if (data.status === 'succeeded') message.success(t('aigc.musicSuccess'))
        else message.error(data?.error || t('aigc.musicFailed'))
      }
    } catch {
      clearInterval(pollTimer!)
      pollTimer = null
      generating.value = false
    }
  }, 3000)
}

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div class="aigc-music-page">
    <div class="aigc-gen-layout">
      <GlassPanel class="aigc-input-panel" variant="subtle">
        <a-form layout="vertical">
          <a-form-item :label="t('aigc.prompt')">
            <a-textarea v-model:value="prompt" :rows="4" :placeholder="t('aigc.musicPromptPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.model')">
            <a-select v-model:value="model" class="model-select-music" :options="musicModelOptions" :placeholder="t('aigc.selectModel')" show-search />
            <div v-if="musicModelOptions.length <= 1" class="aigc-music-model-hint">{{ t('aigc.musicModelEmptyHint') }}</div>
          </a-form-item>
          <a-form-item :label="t('aigc.duration')">
            <a-input-number v-model:value="duration" :min="1" :max="600" style="width: 100%" />
          </a-form-item>
          <GlassButton variant="primary" :loading="generating" @click="generate">
            {{ t('aigc.generate') }}
          </GlassButton>
        </a-form>
      </GlassPanel>
      <div>
        <GlassCard :title="t('aigc.musicStatus')" class="aigc-result-panel">
          <div v-if="status" class="aigc-music-status">
            <a-descriptions :column="1" bordered size="small">
              <a-descriptions-item :label="t('aigc.status')">{{ status.status }}</a-descriptions-item>
              <a-descriptions-item :label="t('aigc.progress')">{{ status.progress ?? 0 }}%</a-descriptions-item>
              <a-descriptions-item v-if="status.url" :label="t('aigc.musicUrl')">
                <a :href="withFileToken(status.url)" target="_blank">{{ status.url }}</a>
              </a-descriptions-item>
            </a-descriptions>
            <a-progress :percent="status.progress ?? 0" :status="status.status === 'failed' ? 'exception' : 'active'" />
            <div v-if="status.error" class="aigc-music-error">{{ status.error }}</div>
            <div v-if="status.url && status.status === 'succeeded'" class="aigc-music-player">
              <audio controls :src="withFileToken(status.url)" />
              <a :href="withFileToken(status.url)" :download="status.url.split('/').pop()" class="aigc-download">
                {{ t('aigc.download') }}
              </a>
            </div>
          </div>
          <a-empty v-else :description="t('aigc.noMusic')" />
        </GlassCard>
        <AigcHistoryList />
      </div>
    </div>
  </div>
</template>

<style scoped>
.aigc-music-status {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.aigc-music-model-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--nr-text-secondary, rgba(255, 255, 255, 0.65));
}

.aigc-music-error {
  font-size: 12px;
  color: var(--nr-danger, var(--nr-error));
}

.aigc-music-player audio {
  width: 100%;
}
</style>
