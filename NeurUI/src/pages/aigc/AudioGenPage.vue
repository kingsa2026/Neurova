<script setup lang="ts">
/**
 * AIGC 音频生成页（2026-09-14 R1 拆分；R2 音色真实化）。
 * JSON 契约（批次1）：{code,data:{url,path,task_id}}；code=-1 诚实失败不误报成功。
 * R2：音色下拉来自 GET /generation/voices（引擎真实枚举）；引擎不可用时
 * 仅保留 default 项（服务端默认音色）——不再硬编码 OpenAI 别名假列表。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { generateAudio as apiGenerateAudio, listGenerationVoices, type VoiceOption } from '@/api/modules/generation'
import { withFileToken } from '@/utils/genFiles'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import AigcHistoryList from '@/components/aigc/AigcHistoryList.vue'

const { t } = useI18n()

const text = ref('')
const voice = ref('default')
const speed = ref(1.0)
const generating = ref(false)
const audioUrl = ref('')
const voices = ref<VoiceOption[]>([])

const voiceOptions = computed(() => {
  if (!voices.value.length) {
    return [{ label: t('aigc.voiceDefault'), value: 'default' }]
  }
  // 中文音色排前（本地化体验），其余保持引擎顺序
  return [...voices.value]
    .sort((a, b) => Number(b.locale?.startsWith('zh') ?? false) - Number(a.locale?.startsWith('zh') ?? false))
    .map((v) => ({ label: v.label, value: v.id }))
})

onMounted(async () => {
  try {
    const res: any = await listGenerationVoices()
    voices.value = res?.data?.voices ?? []
  } catch {
    voices.value = []
  }
})

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
            <a-select v-model:value="voice" class="voice-select" :options="voiceOptions" :placeholder="t('aigc.selectVoice')" />
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
