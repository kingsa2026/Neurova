<script setup lang="ts">
/**
 * AIGC 创作专区（2026-09-14 R1 承接批次4 一键成片；R4/R5 扩为项目化四 Phase 向导）。
 *
 * 当前形态：主题 → 实例化内置短剧模板 → run/stream 工作流 → SSE 步骤点亮 →
 * 连播成片（SlideshowPlayer）/FFmpeg 成片视频。与画布引擎同一底座。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useWorkflowRun } from '@/composables/useWorkflowRun'
import { withFileToken } from '@/utils/genFiles'
import SlideshowPlayer from '@/components/aigc/SlideshowPlayer.vue'
import type { SlideshowItem } from '@/components/aigc/types'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()
const router = useRouter()

const SHORT_DRAMA_TEMPLATE_ID = 'template_short_drama'
const theme = ref('')
const genre = ref('都市逆袭')
const style = ref('cinematic')
const aspect = ref('9:16 竖屏')
const provider = ref('openai')

const {
  running,
  steps,
  outputs,
  workflowId: studioWorkflowId,
  runTemplate,
} = useWorkflowRun()

const genreOptions = [
  '都市逆袭', '甜宠恋爱', '悬疑惊悚', '古装权谋', '战神归来',
].map((g) => ({ label: g, value: g }))
const aspectOptions = [
  { label: '9:16 竖屏', value: '9:16 竖屏' },
  { label: '16:9 横屏', value: '16:9 横屏' },
  { label: '1:1 方形', value: '1:1 方形' },
]
const providerOptions = [
  { label: 'OpenAI 兼容', value: 'openai' },
  { label: '通义万相/百炼', value: 'wanx' },
  { label: '火山 Seedream', value: 'ark' },
  { label: 'ComfyUI 自建', value: 'comfyui' },
]

async function run() {
  if (!theme.value.trim()) return
  const outcome = await runTemplate(
    SHORT_DRAMA_TEMPLATE_ID,
    `短剧-${theme.value.trim().slice(0, 20)}`,
    {
      theme: theme.value.trim(),
      genre: genre.value,
      style: style.value.trim() || 'cinematic',
      aspect_ratio: aspect.value,
      image_provider: provider.value,
    },
  )
  if (outcome.ok) message.success(t('aigc.studioOk'))
  else message.error(outcome.error || t('aigc.generateError'))
}

const studioItems = computed<SlideshowItem[]>(() => {
  const o = (outputs.value || {}) as any
  const images: any[] = o.images || []
  const sb: any[] = o.storyboard || []
  const audio: any[] = o.audio || []
  return images.map((img, i) => ({
    shot: img.shot ?? i + 1,
    url: img.url || '',
    path: img.path || '',
    prompt: img.prompt || '',
    description: sb[i]?.description || sb[i]?.narration || '',
    narration: sb[i]?.narration || '',
    audio: audio[i]?.url || '',
  }))
})

const composedVideoUrl = computed<string>(() => {
  const compose = (outputs.value as any)?.compose || {}
  return String(compose.video_url || '')
})
</script>

<template>
  <div class="aigc-studio-page">
    <div class="aigc-gen-layout">
      <GlassPanel class="aigc-input-panel" variant="subtle">
        <a-form layout="vertical">
          <a-form-item :label="t('aigc.studioTheme')">
            <a-textarea v-model:value="theme" :rows="3" :placeholder="t('aigc.studioThemePlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.studioGenre')">
            <a-select v-model:value="genre" :options="genreOptions" />
          </a-form-item>
          <a-form-item :label="t('aigc.studioStyle')">
            <a-input v-model:value="style" :placeholder="t('aigc.studioStylePlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.studioAspect')">
            <a-select v-model:value="aspect" :options="aspectOptions" />
          </a-form-item>
          <a-form-item :label="t('aigc.studioProvider')">
            <a-select v-model:value="provider" :options="providerOptions" />
          </a-form-item>
          <GlassButton variant="primary" :loading="running" @click="run">
            {{ t('aigc.studioGenerate') }}
          </GlassButton>
        </a-form>
      </GlassPanel>
      <GlassCard :title="t('aigc.result')" class="aigc-result-panel">
        <div v-if="steps.length" class="studio-steps">
          <div v-for="step in steps" :key="step.id" class="studio-step">
            <a-tag :color="step.status === 'success' ? 'success' : step.status === 'failed' ? 'error' : step.status === 'running' ? 'processing' : 'default'">
              {{ step.label }}
            </a-tag>
          </div>
        </div>
        <SlideshowPlayer v-if="studioItems.length" :items="studioItems" />
        <div v-else-if="!running" class="studio-empty-hint">
          <a-empty :description="t('aigc.studioEmpty')" />
        </div>
        <div v-if="composedVideoUrl" class="studio-composed">
          <video controls :src="withFileToken(composedVideoUrl)" style="width: 100%; border-radius: 10px" />
          <a :href="withFileToken(composedVideoUrl)" :download="composedVideoUrl.split('/').pop()" class="aigc-download">{{ t('aigc.download') }}</a>
        </div>
        <a v-if="studioWorkflowId" class="studio-open" @click="router.push('/collaboration/workflows')">
          {{ t('aigc.studioOpenWorkflow') }}
        </a>
      </GlassCard>
    </div>
  </div>
</template>

<style scoped>
.studio-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.studio-composed {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
}

.studio-open {
  display: inline-block;
  margin-top: 12px;
  font-size: 13px;
  color: var(--nr-accent, #4096ff);
  cursor: pointer;
}
</style>
