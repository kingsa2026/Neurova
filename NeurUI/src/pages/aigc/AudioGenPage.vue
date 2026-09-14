<script setup lang="ts">
/**
 * AIGC 音频生成页（2026-09-14 R1 自 AIGCPage 拆分）。
 * JSON 契约（批次1）：{code,data:{url,path,task_id}}；code=-1 诚实失败不误报成功。
 * 音色列表当前仍为引擎别名常量（R2 换 GET /generation/voices 真实列表）。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { generateAudio as apiGenerateAudio } from '@/api/modules/generation'
import { withFileToken } from '@/utils/genFiles'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import AigcHistoryList from '@/components/aigc/AigcHistoryList.vue'

const { t } = useI18n()

const text = ref('')
const voice = ref('alloy')
const speed = ref(1.0)
const generating = ref(false)
const audioUrl = ref('')

const voiceOptions = [
  { label: t('aigc.voiceAlloy'), value: 'alloy' },
  { label: t('aigc.voiceEcho'), value: 'echo' },
  { label: t('aigc.voiceFable'), value: 'fable' },
  { label: t('aigc.voiceOnyx'), value: 'onyx' },
  { label: t('aigc.voiceNova'), value: 'nova' },
  { label: t('aigc.voiceShimmer'), value: 'shimmer' },
]

async function synthesize() {
  if (!text.value.trim()) return
  generating.value = true
  audioUrl.value = ''
  try {
    const res: any = await apiGenerateAudio({
      text: text.value,
      voice: voice.value,
      speed: speed.value,
    })
    if (res?.code === -1) {
      message.error(res?.message || t('aigc.generateError'))
      return
    }
    const data = res?.data ?? res
    audioUrl.value = data?.url ?? data?.audio_url ?? ''
    if (!audioUrl.value) {
      message.error(t('aigc.generateError'))
      return
    }
    message.success(t('aigc.audioSuccess'))
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="aigc-audio-page">
    <div class="aigc-gen-layout">
      <GlassPanel class="aigc-input-panel" variant="subtle">
        <a-form layout="vertical">
          <a-form-item :label="t('aigc.textInput')">
            <a-textarea v-model:value="text" :rows="4" :placeholder="t('aigc.audioPromptPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.voice')">
            <a-select v-model:value="voice" :options="voiceOptions" :placeholder="t('aigc.selectVoice')" />
          </a-form-item>
          <a-form-item :label="t('aigc.speed')">
            <a-slider v-model:value="speed" :min="0.5" :max="2" :step="0.05" />
          </a-form-item>
          <GlassButton variant="primary" :loading="generating" @click="synthesize">
            {{ t('aigc.synthesize') }}
          </GlassButton>
        </a-form>
      </GlassPanel>
      <div>
        <GlassCard :title="t('aigc.audioResult')" class="aigc-result-panel">
          <div v-if="audioUrl" class="aigc-audio-player">
            <audio controls :src="withFileToken(audioUrl)" />
            <a :href="withFileToken(audioUrl)" :download="audioUrl.split('/').pop()" class="aigc-download" style="display: inline-block; margin-top: 8px">
              {{ t('aigc.download') }}
            </a>
          </div>
          <a-empty v-else :description="t('aigc.noAudio')" />
        </GlassCard>
        <AigcHistoryList kind="audio" />
      </div>
    </div>
  </div>
</template>
