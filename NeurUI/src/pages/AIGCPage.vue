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
                <a-select v-model:value="textModel" class="model-select-text" :options="textModelOptions" :placeholder="t('aigc.selectModel')" show-search />
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
              <a-form-item :label="t('aigc.refImage')">
                <a-upload :show-upload-list="false" accept="image/*" :custom-request="(o: any) => onRefUpload(o.file, 'image')">
                  <GlassButton size="sm">{{ t('common.upload') }}</GlassButton>
                </a-upload>
                <div v-if="imageRefImages.length" class="ref-chips">
                  <span v-for="(p, i) in imageRefImages" :key="i" class="ref-chip">
                    {{ refFileName(p) }}<button class="ref-chip-x" type="button" @click="removeRef('image', i)">✕</button>
                  </span>
                </div>
              </a-form-item>
              <a-form-item :label="t('aigc.model')">
                <a-select v-model:value="imageModel" class="model-select-image" :options="imageModelOptions" :placeholder="t('aigc.selectModel')" show-search />
              </a-form-item>
              <GlassButton variant="primary" :loading="imageGenerating" @click="generateImage">
                {{ t('aigc.generate') }}
              </GlassButton>
            </a-form>
          </GlassPanel>
          <GlassCard :title="t('aigc.gallery')" class="result-panel">
            <div v-if="imageResults.length" class="image-gallery">
              <div v-for="(img, idx) in imageResults" :key="idx" class="gallery-item" @click="previewImage(img)">
                <img :src="withFileToken(img.url)" :alt="img.prompt" />
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
              <audio controls :src="withFileToken(audioUrl)" />
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
              <a-form-item :label="t('aigc.model')">
                <a-select v-model:value="videoModel" class="model-select-video" :options="videoModelOptions" :placeholder="t('aigc.selectModel')" show-search />
              </a-form-item>
              <!-- B2-c 参数面：协议/服务商凭据/时长/分辨率/参考图/音频 -->
              <a-form-item :label="t('aigc.protocol')">
                <a-select v-model:value="videoProtocol" allow-clear :placeholder="t('aigc.protocolAuto')">
                  <a-select-option value="wan">wan（百炼 Wan）</a-select-option>
                  <a-select-option value="seedance2">seedance2（火山 Ark）</a-select-option>
                  <a-select-option value="veo">veo（Gemini）</a-select-option>
                </a-select>
              </a-form-item>
              <a-form-item :label="t('aigc.providerId')">
                <a-input v-model:value="videoProviderId" allow-clear :placeholder="t('aigc.providerIdHint')" />
              </a-form-item>
              <a-form-item :label="t('aigc.duration')">
                <a-input-number v-model:value="videoDuration" :min="1" :max="60" style="width: 100%" />
              </a-form-item>
              <a-form-item :label="t('aigc.resolution')">
                <a-select v-model:value="videoResolution">
                  <a-select-option value="480p">480p</a-select-option>
                  <a-select-option value="720p">720p</a-select-option>
                  <a-select-option value="1080p">1080p</a-select-option>
                </a-select>
              </a-form-item>
              <a-form-item :label="t('aigc.refImage')">
                <a-upload :show-upload-list="false" accept="image/*" :custom-request="(o: any) => onRefUpload(o.file, 'video')">
                  <GlassButton size="sm">{{ t('common.upload') }}</GlassButton>
                </a-upload>
                <div v-if="videoRefImages.length" class="ref-chips">
                  <span v-for="(p, i) in videoRefImages" :key="i" class="ref-chip">
                    {{ refFileName(p) }}<button class="ref-chip-x" type="button" @click="removeRef('video', i)">✕</button>
                  </span>
                </div>
              </a-form-item>
              <a-form-item :label="t('aigc.audio')">
                <a-select v-model:value="videoAudio" allow-clear :placeholder="t('aigc.protocolAuto')">
                  <a-select-option :value="true">{{ t('common.yes') }}</a-select-option>
                  <a-select-option :value="false">{{ t('common.no') }}</a-select-option>
                </a-select>
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
                  <a :href="withFileToken(videoStatus.url)" target="_blank">{{ videoStatus.url }}</a>
                </a-descriptions-item>
              </a-descriptions>
              <a-progress :percent="videoStatus.progress ?? 0" :status="videoStatus.status === 'failed' ? 'exception' : 'active'" />
            </div>
            <a-empty v-else :description="t('aigc.noVideo')" />
          </GlassCard>
        </div>
      </a-tab-pane>
    </a-tabs>

    <!-- 批次2：历史记录面板（消费 GET /generation/tasks，PRINTFILM 工具创作记录对标） -->
    <GlassPanel v-if="activeTab === 'history'" class="history-panel" variant="subtle">
      <div class="history-toolbar">
        <a-radio-group v-model:value="historyKind" size="small" @change="onHistoryKindChange">
          <a-radio-button value="">{{ t('aigc.all') }}</a-radio-button>
          <a-radio-button value="image">{{ t('aigc.image') }}</a-radio-button>
          <a-radio-button value="video">{{ t('aigc.video') }}</a-radio-button>
          <a-radio-button value="audio">{{ t('aigc.audio') }}</a-radio-button>
        </a-radio-group>
        <GlassButton size="sm" @click="loadHistory(historyKind || undefined)">{{ t('common.refresh') }}</GlassButton>
      </div>
      <div v-if="historyTasks.length" class="history-list">
        <div v-for="task in historyTasks" :key="task.task_id" class="history-item">
          <div class="history-thumb">
            <img v-if="task.kind === 'image' && task.url" :src="withFileToken(task.url)" :alt="task.prompt" />
            <span v-else class="history-kind-badge">{{ task.kind }}</span>
          </div>
          <div class="history-info">
            <div class="history-prompt">{{ task.prompt || '—' }}</div>
            <div class="history-meta">
              <a-tag :color="taskStatusColor(task.status)">{{ taskStatusText(task.status) }}</a-tag>
              <span v-if="task.model">{{ task.model }}</span>
              <span>{{ formatTaskTime(task.submitted_at) }}</span>
            </div>
            <div v-if="task.error" class="history-error">{{ task.error }}</div>
          </div>
          <div class="history-actions">
            <a v-if="task.url" :href="withFileToken(task.url)" :download="task.url.split('/').pop()" class="history-download">
              {{ t('aigc.download') }}
            </a>
          </div>
        </div>
      </div>
      <a-empty v-else :description="t('aigc.noHistory')" />
    </GlassPanel>

    <!-- Image Preview Modal -->
    <a-modal v-model:open="imagePreviewVisible" :footer="null" width="680px">
      <img :src="withFileToken(imagePreviewUrl)" alt="Preview" style="width: 100%" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { request } from '@/api'
import { listModels } from '@/api/modules/models'
import {
  generateText as apiGenerateText,
  generateImage as apiGenerateImage,
  listGenerationTasks,
  type GenerationTask,
} from '@/api/modules/generation'
import { uploadFile } from '@/api/modules/files'
import { withFileToken } from '@/utils/genFiles'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { renderMarkdown } from '@/utils/markdown'

const { t } = useI18n()

const activeTab = ref<'text' | 'image' | 'audio' | 'video' | 'history'>('text')

// 图像风格模板（批次1）：原实现错接 GET /v1/image/templates —— 那是 Docker
// 镜像构建模板（base_image/dockerfile），与图像风格无关；且提交的 style 字段
// 后端 ImageGenerationRequest 无此字段，静默丢弃零作用。改为内置风格常量，
// 生成时把风格提示词注入 prompt（火宝式「风格注入每镜提示词」）。
const STYLE_TEMPLATES: { value: string; hint: string }[] = [
  { value: 'default', hint: '' },
  { value: 'photorealistic', hint: 'photorealistic, ultra-detailed, 8k' },
  { value: 'anime', hint: 'anime style, vibrant colors, clean lineart' },
  { value: 'oil-painting', hint: 'oil painting style, visible textured brush strokes' },
]

// --- 能力感知模型下拉（2026-09-03）---
// 数据源 = GET /models（capabilities 由后端自动检测并持久化），
// 各 Tab 按 capability 过滤；首选项恒为 auto（LLMRouter 自动路由）。
interface CapModel {
  id: string
  name: string
  provider: string
  capabilities: string[]
}

const allCapModels = ref<CapModel[]>([])
const TEMPLATE_LABEL_KEYS: Record<string, string> = {
  default: 'default',
  photorealistic: 'photorealistic',
  anime: 'anime',
  'oil-painting': 'oilPainting',
}
const imageTemplateOptions = computed(() =>
  STYLE_TEMPLATES.map((tpl) => ({ label: t(`aigc.${TEMPLATE_LABEL_KEYS[tpl.value]}`), value: tpl.value })))

function normalizeCapModel(m: any): CapModel {
  return {
    id: m.model_id || m.id || m.name || 'unknown',
    name: m.name || m.model_id || m.id || 'Unknown',
    provider: m.provider || m.provider_id || '',
    capabilities: Array.isArray(m.capabilities) ? m.capabilities.map(String) : [],
  }
}

function modelsWithCap(cap: string): CapModel[] {
  const seen = new Set<string>()
  return allCapModels.value.filter((m) => {
    if (!m.capabilities.includes(cap) || seen.has(m.id)) return false
    seen.add(m.id)
    return true
  })
}

function capOptions(cap: string) {
  return [
    { label: t('ui.autoRoute'), value: 'auto' },
    ...modelsWithCap(cap).map((m) => ({
      label: m.provider ? `${m.provider} / ${m.name}` : m.name,
      value: m.id,
    })),
  ]
}

const textModelOptions = computed(() => capOptions('text'))
const imageModelOptions = computed(() => capOptions('image_generation'))
const videoModelOptions = computed(() => capOptions('video_generation'))

// --- 批次2：历史记录（账本快照 + 未决自动刷新）---
const historyTasks = ref<GenerationTask[]>([])
const historyKind = ref('')
let historyPollTimer: ReturnType<typeof setInterval> | null = null

async function loadHistory(kind?: string) {
  try {
    const res: any = await listGenerationTasks(kind ? ({ kind } as any) : undefined)
    historyTasks.value = res?.data?.tasks ?? []
  } catch {
    /* 保留已渲染列表，错误不打断浏览 */
  }
  ensureHistoryPolling()
}

function onHistoryKindChange() {
  loadHistory(historyKind.value || undefined)
}

function ensureHistoryPolling() {
  const pending = historyTasks.value.some(
    (task) => task.status === 'submitted' || task.status === 'running')
  if (pending && !historyPollTimer) {
    historyPollTimer = setInterval(() => {
      loadHistory(historyKind.value || undefined)
    }, 5000)
  } else if (!pending && historyPollTimer) {
    clearInterval(historyPollTimer)
    historyPollTimer = null
  }
}

function taskStatusText(status: string): string {
  const keyMap: Record<string, string> = {
    submitted: 'aigc.stSubmitted',
    running: 'aigc.stRunning',
    succeeded: 'aigc.stSucceeded',
    failed: 'aigc.stFailed',
  }
  return keyMap[status] ? t(keyMap[status]) : status
}

function taskStatusColor(status: string): string {
  const colorMap: Record<string, string> = {
    submitted: 'default',
    running: 'processing',
    succeeded: 'success',
    failed: 'error',
  }
  return colorMap[status] ?? 'default'
}

function formatTaskTime(ts: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString()
}

watch(activeTab, (tab) => {
  if (tab === 'history') loadHistory(historyKind.value || undefined)
})

onUnmounted(() => {
  // BUG-24 修复：卸载时清理视频轮询定时器（原实现泄漏直到任务终态）
  if (videoPollTimer) {
    clearInterval(videoPollTimer)
    videoPollTimer = null
  }
  if (historyPollTimer) {
    clearInterval(historyPollTimer)
    historyPollTimer = null
  }
})

onMounted(async () => {
  try {
    const raw = (await listModels()) as any
    const data = raw?.data ?? raw
    const list = Array.isArray(data) ? data : (data?.models ?? data?.data ?? [])
    allCapModels.value = list.map(normalizeCapModel)
  } catch { /* use defaults */ }
})

// --- Text ---
const textPrompt = ref('')
const textModel = ref('auto')
const textGenerating = ref(false)
const textResult = ref('')

// 安全审计 M3: 原实现为手写正则伪 MD 直出 v-html，模型返回内容（可含用户
// 提示词注入的 HTML）未转义 → 存储型/DOM XSS。改用共享的 renderMarkdown
// （marked + DOMPurify 白名单），与 ChatPage 同源净化。
const renderedText = computed(() => renderMarkdown(textResult.value, t('common.copy')))

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
const imageModel = ref('auto')
const imageGenerating = ref(false)
const imageResults = ref<{ url: string; prompt: string }[]>([])
const imagePreviewVisible = ref(false)
const imagePreviewUrl = ref('')

// --- 批次3：参考图上传（复用 /files/upload，后端允许根含 storage 上传目录）---
const imageRefImages = ref<string[]>([])
const videoRefImages = ref<string[]>([])

async function onRefUpload(file: File | { name?: string; size?: number }, target: 'image' | 'video') {
  const list = target === 'image' ? imageRefImages : videoRefImages
  try {
    const fd = new FormData()
    fd.append('file', file as Blob, (file as any).name || 'ref.png')
    const res: any = await uploadFile(fd)
    const path = res?.data?.path || res?.path
    if (path) {
      list.value.push(path)
    } else {
      message.error(t('aigc.generateError'))
    }
  } catch {
    message.error(t('aigc.generateError'))
  }
}

function removeRef(target: 'image' | 'video', idx: number) {
  const list = target === 'image' ? imageRefImages : videoRefImages
  list.value.splice(idx, 1)
}

function refFileName(p: string): string {
  return p.split(/[\\/]/).pop() || p
}

async function generateImage() {
  if (!imagePrompt.value.trim()) return
  imageGenerating.value = true
  try {
    const tpl = STYLE_TEMPLATES.find((x) => x.value === imageTemplate.value)
    // 批次1：风格模板注入提示词（后端无 style 字段，旧实现发的 style 被静默丢弃）；
    // model=auto 不再当模型名透传（后端已按图像生成能力自动路由，undefined 对齐视频 Tab）
    const styledPrompt = tpl?.hint ? `${imagePrompt.value.trim()}\n${tpl.hint}` : imagePrompt.value.trim()
    const res: any = await apiGenerateImage({
      prompt: styledPrompt,
      model: imageModel.value === 'auto' ? undefined : imageModel.value,
      width: 1024,
      height: 1024,
      ref_images: imageRefImages.value.length ? [...imageRefImages.value] : undefined,
    })
    const data = res?.data ?? res
    // B2-c 契约：/generation/image 返回 images:[{url, path}]（本地化产物），
    // 兼容旧字符串数组形态
    const rawImages: any[] = data?.images ?? data?.urls ?? (data?.url ? [data.url] : [])
    const urls: string[] = rawImages
      .map((i: any) => (typeof i === 'string' ? i : i?.url))
      .filter(Boolean)
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
    // 批次1：后端统一 JSON 契约 {code,data:{url}}；code=-1 是诚实失败（TTS 未就绪/
    // 合成失败），不得再打成功 toast（原实现二进制与 JSON 劈叉，恒显示空播放器）
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
    audioGenerating.value = false
  }
}

// --- Video ---
const videoPrompt = ref('')
const videoModel = ref('auto')
// B2-c：参数面（协议/服务商/时长/分辨率/参考图/音频开关）
const videoProtocol = ref('')
const videoProviderId = ref('')
const videoDuration = ref(5)
const videoResolution = ref('1080p')
const videoAudio = ref<boolean | null>(null)
const videoGenerating = ref(false)
const videoStatus = ref<{ status: string; progress: number; url?: string } | null>(null)
let videoPollTimer: ReturnType<typeof setInterval> | null = null

async function generateVideo() {
  if (!videoPrompt.value.trim()) return
  videoGenerating.value = true
  videoStatus.value = { status: 'pending', progress: 0 }
  try {
    const payload: Record<string, unknown> = {
      prompt: videoPrompt.value,
      model: videoModel.value === 'auto' ? undefined : videoModel.value,
      duration: videoDuration.value,
      resolution: videoResolution.value,
    }
    if (videoProtocol.value) payload.protocol = videoProtocol.value
    if (videoProviderId.value) payload.provider_id = videoProviderId.value
    if (videoRefImages.value.length) payload.ref_images = [...videoRefImages.value]
    if (videoAudio.value !== null) payload.audio = videoAudio.value
    const res: any = await request.post('/generation/video', payload)
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
  // BUG-24 修复：先清旧 timer，防止双 interval 只有最后一个能被清除
  if (videoPollTimer) {
    clearInterval(videoPollTimer)
    videoPollTimer = null
  }
  videoPollTimer = setInterval(async () => {
    try {
      // B2-c：后端真实轮询端点（账本+协议轮询），succeeded=完成
      const res: any = await request.get(`/generation/video/status/${taskId}`)
      const data = res?.data ?? res
      videoStatus.value = {
        status: data?.status ?? 'processing',
        progress: data?.status === 'succeeded' ? 100 : videoStatus.value?.progress ?? 0,
        url: data?.url,
      }
      if (data?.status === 'succeeded' || data?.status === 'failed') {
        clearInterval(videoPollTimer!)
        videoPollTimer = null
        videoGenerating.value = false
        if (data.status === 'succeeded') message.success(t('aigc.videoSuccess'))
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
}

.gallery-item:hover {
  background: rgba(255,255,255,0.04);
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

/* 批次2：历史记录面板 */
.history-panel {
  padding: 16px 20px;
}

.history-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.history-item {
  display: grid;
  grid-template-columns: 64px 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--nr-bg-elevated, rgba(255, 255, 255, 0.04));
}

.history-thumb img {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 8px;
}

.history-kind-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  text-transform: uppercase;
  color: var(--nr-text-secondary);
  background: rgba(125, 125, 125, 0.15);
}

.history-prompt {
  font-size: 13px;
  color: var(--nr-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--nr-text-tertiary, var(--nr-text-secondary));
}

.history-error {
  margin-top: 4px;
  font-size: 12px;
  color: var(--nr-danger, #ff4d4f);
}

.history-download {
  font-size: 13px;
  color: var(--nr-accent, #4096ff);
}

/* 批次3：参考图上传 chips */
.ref-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.ref-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: rgba(125, 125, 125, 0.15);
}

.ref-chip-x {
  border: none;
  background: transparent;
  cursor: pointer;
  color: inherit;
  font-size: 11px;
  padding: 0;
}
</style>
