<template>
  <div class="aigc-page">
    <!-- Header -->
    <GlassPanel class="aigc-header">
      <h2 class="page-title">{{ t('aigc.title') }}</h2>
    </GlassPanel>

    <!-- Tabs -->
    <a-tabs v-model:activeKey="activeTab" class="aigc-tabs">
      <!-- TEXT TAB -->
      <a-tab-pane key="text" :tab="t('aigc.text')">
        <div class="generation-layout">
          <GlassPanel class="input-panel" variant="subtle">
            <a-form layout="vertical">
              <a-form-item :label="t('aigc.prompt')">
                <a-textarea v-model:value="textPrompt" :rows="6" :placeholder="t('aigc.textPromptPlaceholder')" />
              </a-form-item>
              <a-form-item :label="t('aigc.model')">
                <a-select v-model:value="textModel" :options="textModels" :placeholder="t('aigc.selectModel')" show-search />
              </a-form-item>
              <GlassButton variant="primary" :loading="textGenerating" @click="generateText">
                {{ t('aigc.generate') }}
              </GlassButton>
            </a-form>
          </GlassPanel>
          <GlassCard :title="t('aigc.result')" class="result-panel">
            <div v-if="textResult" class="text-result" v-html="renderedText" />
            <a-empty v-else :description="t('aigc.noResult')" />
          </GlassCard>
        </div>
      </a-tab-pane>

      <!-- IMAGE TAB -->
      <a-tab-pane key="image" :tab="t('aigc.image')">
        <div class="generation-layout">
          <GlassPanel class="input-panel" variant="subtle">
            <a-form layout="vertical">
              <a-form-item :label="t('aigc.prompt')">
                <a-textarea v-model:value="imagePrompt" :rows="4" :placeholder="t('aigc.imagePromptPlaceholder')" />
              </a-form-item>
              <a-form-item :label="t('aigc.template')">
                <a-select v-model:value="imageTemplate" :options="imageTemplateOptions" :placeholder="t('aigc.selectTemplate')" show-search />
              </a-form-item>
              <GlassButton variant="primary" :loading="imageGenerating" @click="generateImage">
                {{ t('aigc.generate') }}
              </GlassButton>
            </a-form>
          </GlassPanel>
          <GlassCard :title="t('aigc.gallery')" class="result-panel">
            <div v-if="imageResults.length" class="image-gallery">
              <div v-for="(img, idx) in imageResults" :key="idx" class="gallery-item" @click="previewImage(img)">
                <img :src="img.url" :alt="img.prompt" />
              </div>
            </div>
            <a-empty v-else :description="t('aigc.noImages')" />
          </GlassCard>
        </div>
      </a-tab-pane>

      <!-- AUDIO TAB -->
      <a-tab-pane key="audio" :tab="t('aigc.audio')">
        <div class="generation-layout">
          <GlassPanel class="input-panel" variant="subtle">
            <a-form layout="vertical">
              <a-form-item :label="t('aigc.textInput')">
                <a-textarea v-model:value="audioText" :rows="4" :placeholder="t('aigc.audioPromptPlaceholder')" />
              </a-form-item>
              <a-form-item :label="t('aigc.voice')">
                <a-select v-model:value="audioVoice" :options="voiceOptions" :placeholder="t('aigc.selectVoice')" />
              </a-form-item>
              <GlassButton variant="primary" :loading="audioGenerating" @click="generateAudio">
                {{ t('aigc.synthesize') }}
              </GlassButton>
            </a-form>
          </GlassPanel>
          <GlassCard :title="t('aigc.audioResult')" class="result-panel">
            <div v-if="audioUrl" class="audio-player">
              <audio controls :src="audioUrl" />
            </div>
            <a-empty v-else :description="t('aigc.noAudio')" />
          </GlassCard>
        </div>
      </a-tab-pane>

      <!-- VIDEO TAB -->
      <a-tab-pane key="video" :tab="t('aigc.video')">
        <div class="generation-layout">
          <GlassPanel class="input-panel" variant="subtle">
            <a-form layout="vertical">
              <a-form-item :label="t('aigc.prompt')">
                <a-textarea v-model:value="videoPrompt" :rows="4" :placeholder="t('aigc.videoPromptPlaceholder')" />
              </a-form-item>
              <GlassButton variant="primary" :loading="videoGenerating" @click="generateVideo">
                {{ t('aigc.generate') }}
              </GlassButton>
            </a-form>
          </GlassPanel>
          <GlassCard :title="t('aigc.videoStatus')" class="result-panel">
            <div v-if="videoStatus" class="video-status">
              <a-descriptions :column="1" bordered size="small">
                <a-descriptions-item :label="t('aigc.status')">{{ videoStatus.status }}</a-descriptions-item>
                <a-descriptions-item :label="t('aigc.progress')">{{ videoStatus.progress ?? 0 }}%</a-descriptions-item>
                <a-descriptions-item v-if="videoStatus.url" :label="t('aigc.videoUrl')">
                  <a :href="videoStatus.url" target="_blank">{{ videoStatus.url }}</a>
                </a-descriptions-item>
              </a-descriptions>
              <a-progress :percent="videoStatus.progress ?? 0" :status="videoStatus.status === 'failed' ? 'exception' : 'active'" />
            </div>
            <a-empty v-else :description="t('aigc.noVideo')" />
          </GlassCard>
        </div>
      </a-tab-pane>
    </a-tabs>

    <!-- Image Preview Modal -->
    <a-modal v-model:open="imagePreviewVisible" :footer="null" width="680px">
      <img :src="imagePreviewUrl" alt="Preview" style="width: 100%" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { request } from '@/api'
import { getAdapters } from '@/api/modules/model-adapter'
import { getTemplates as getImageTemplates } from '@/api/modules/image'
import { generateText as apiGenerateText, generateImage as apiGenerateImage } from '@/api/modules/generation'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

const activeTab = ref<'text' | 'image' | 'audio' | 'video'>('text')

// --- Dynamic options from backend ---
const textModels = ref<{ label: string; value: string }[]>([])
const imageTemplateOptions = ref<{ label: string; value: string }[]>([])

onMounted(async () => {
  try {
    const [adaptersRes, templatesRes] = await Promise.allSettled([getAdapters(), getImageTemplates()])
    if (adaptersRes.status === 'fulfilled') {
      const adapters = adaptersRes.value?.data?.adapters ?? []
      const models: { label: string; value: string }[] = []
      for (const a of adapters) {
        for (const m of a.models ?? []) {
          models.push({ label: `${a.name} / ${m}`, value: m })
        }
      }
      textModels.value = models.length ? models : [
        { label: 'GPT-4', value: 'gpt-4' },
        { label: 'GPT-3.5', value: 'gpt-3.5-turbo' },
        { label: 'Claude 3', value: 'claude-3' },
      ]
    }
    if (templatesRes.status === 'fulfilled') {
      const templates = templatesRes.value?.data?.templates ?? []
      imageTemplateOptions.value = templates.map((t: any) => ({ label: t.name ?? t.description ?? t.base_image, value: t.name }))
    }
  } catch { /* use defaults */ }
  if (!imageTemplateOptions.value.length) {
    imageTemplateOptions.value = [
      { label: t('aigc.default'), value: 'default' },
      { label: t('aigc.photorealistic'), value: 'photorealistic' },
      { label: t('aigc.anime'), value: 'anime' },
      { label: t('aigc.oilPainting'), value: 'oil-painting' },
    ]
  }
})

// --- Text ---
const textPrompt = ref('')
const textModel = ref('gpt-4')
const textGenerating = ref(false)
const textResult = ref('')

const renderedText = computed(() => {
  // Basic markdown: bold, italic, code blocks, line breaks
  return textResult.value
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br />')
})

async function generateText() {
  if (!textPrompt.value.trim()) return
  textGenerating.value = true
  textResult.value = ''
  try {
    const res: any = await apiGenerateText({
      prompt: textPrompt.value,
      model: textModel.value,
    })
    const data = res?.data ?? res
    textResult.value = data?.content ?? data?.text ?? ''
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    textGenerating.value = false
  }
}

// --- Image ---
const imagePrompt = ref('')
const imageTemplate = ref('default')
const imageGenerating = ref(false)
const imageResults = ref<{ url: string; prompt: string }[]>([])
const imagePreviewVisible = ref(false)
const imagePreviewUrl = ref('')

async function generateImage() {
  if (!imagePrompt.value.trim()) return
  imageGenerating.value = true
  try {
    const res: any = await apiGenerateImage({
      prompt: imagePrompt.value,
      style: imageTemplate.value,
    })
    const data = res?.data ?? res
    const urls: string[] = data?.urls ?? data?.images ?? (data?.url ? [data.url] : [])
    for (const url of urls) {
      imageResults.value.unshift({ url, prompt: imagePrompt.value })
    }
    message.success(t('aigc.imageSuccess'))
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    imageGenerating.value = false
  }
}

function previewImage(img: { url: string }) {
  imagePreviewUrl.value = img.url
  imagePreviewVisible.value = true
}

// --- Audio ---
const audioText = ref('')
const audioVoice = ref('alloy')
const audioGenerating = ref(false)
const audioUrl = ref('')

const voiceOptions = [
  { label: t('aigc.voiceAlloy'), value: 'alloy' },
  { label: t('aigc.voiceEcho'), value: 'echo' },
  { label: t('aigc.voiceFable'), value: 'fable' },
  { label: t('aigc.voiceOnyx'), value: 'onyx' },
  { label: t('aigc.voiceNova'), value: 'nova' },
  { label: t('aigc.voiceShimmer'), value: 'shimmer' },
]

async function generateAudio() {
  if (!audioText.value.trim()) return
  audioGenerating.value = true
  audioUrl.value = ''
  try {
    const res: any = await request.post('/generation/audio', {
      text: audioText.value,
      voice: audioVoice.value,
    })
    const data = res?.data ?? res
    audioUrl.value = data?.url ?? data?.audio_url ?? ''
    message.success(t('aigc.audioSuccess'))
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    audioGenerating.value = false
  }
}

// --- Video ---
const videoPrompt = ref('')
const videoGenerating = ref(false)
const videoStatus = ref<{ status: string; progress: number; url?: string } | null>(null)
let videoPollTimer: ReturnType<typeof setInterval> | null = null

async function generateVideo() {
  if (!videoPrompt.value.trim()) return
  videoGenerating.value = true
  videoStatus.value = { status: 'pending', progress: 0 }
  try {
    const res: any = await request.post('/generation/video', { prompt: videoPrompt.value })
    const data = res?.data ?? res
    const taskId = data?.task_id ?? data?.id
    videoStatus.value = { status: data?.status ?? 'processing', progress: data?.progress ?? 0 }
    if (taskId) {
      pollVideoStatus(taskId)
    }
  } catch {
    message.error(t('aigc.generateError'))
    videoGenerating.value = false
  }
}

function pollVideoStatus(taskId: string) {
  videoPollTimer = setInterval(async () => {
    try {
      const res: any = await request.get(`/generation/video/${taskId}`)
      const data = res?.data ?? res
      videoStatus.value = {
        status: data?.status ?? 'processing',
        progress: data?.progress ?? 0,
        url: data?.url,
      }
      if (data?.status === 'completed' || data?.status === 'failed') {
        clearInterval(videoPollTimer!)
        videoPollTimer = null
        videoGenerating.value = false
        if (data.status === 'completed') message.success(t('aigc.videoSuccess'))
        else message.error(t('aigc.videoFailed'))
      }
    } catch {
      clearInterval(videoPollTimer!)
      videoPollTimer = null
      videoGenerating.value = false
    }
  }, 3000)
}
</script>

<style scoped>
.aigc-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.aigc-header {
  padding: 16px 24px;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.generation-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 20px;
  align-items: start;
}

.input-panel {
  position: sticky;
  top: 0;
}

.result-panel {
  min-height: 300px;
}

.text-result {
  font-size: 14px;
  line-height: 1.7;
  color: var(--nr-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.text-result :deep(pre) {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}

.text-result :deep(code) {
  font-family: var(--nr-font-mono);
  font-size: 13px;
}

.image-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.gallery-item {
  aspect-ratio: 1;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s;
}

.gallery-item:hover {
  transform: scale(1.03);
}

.gallery-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.audio-player audio {
  width: 100%;
}

.video-status {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
