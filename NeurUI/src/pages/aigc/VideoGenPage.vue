<script setup lang="ts">
/**
 * AIGC 视频生成页（2026-09-14 R1 自 AIGCPage 拆分）。
 * 异步提交 + 账本轮询（B2-c 参数面保持）；model=auto → 后端按视频能力路由；
 * 参考图上传 → ref_images；未决任务轮询卸载清理（BUG-24）保持。
 */
import { onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { request } from '@/api'
import { generateImage, submitVideo, resolveGeneration, type VideoGenerationPayload } from '@/api/modules/generation'
import { uploadFile } from '@/api/modules/files'
import { useAigcModels } from '@/composables/useAigcModels'
import { withFileToken } from '@/utils/genFiles'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import AigcHistoryList from '@/components/aigc/AigcHistoryList.vue'

const { t } = useI18n()
const { videoModelOptions, providerOf } = useAigcModels()

const prompt = ref('')
const model = ref('auto')
const duration = ref(5)
// 2026-09-15 自适应：协议/服务商由后端按「模型→服务商 base_url」同源推导
// （GET /generation/resolve），不再手填；auto 态提交时由后端按能力路由+推导。
const derived = ref<{ protocol: string; providerId: string } | null>(null)
let deriveSeq = 0
watch(model, async (m) => {
  if (m === 'auto') { derived.value = null; return }
  const seq = ++deriveSeq
  const pid = providerOf(m)
  try {
    const res: any = await resolveGeneration('video', m, pid || undefined)
    const d = res?.data ?? res
    if (seq === deriveSeq && d?.protocol) {
      derived.value = { protocol: d.protocol, providerId: d.provider_id || pid }
    }
  } catch { /* 推导服务不可用不阻断：提交路径服务端同样自适应推导 */ }
})
const resolution = ref('1080p')
const refImages = ref<string[]>([])
const withAudio = ref<boolean | null>(null)
// R2 两段式：先出静帧，静帧作首帧再生成视频
const staticFirst = ref(true)
const generating = ref(false)
const status = ref<{ status: string; progress: number; url?: string } | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function onRefUpload(file: File) {
  try {
    const fd = new FormData()
    fd.append('file', file, (file as any).name || 'frame.png')
    const res: any = await uploadFile(fd)
    const path = res?.data?.path || res?.path
    if (path) refImages.value.push(path)
    else message.error(t('aigc.generateError'))
  } catch {
    message.error(t('aigc.generateError'))
  }
}

function refFileName(p: string): string {
  return p.split(/[\\/]/).pop() || p
}

async function generate() {
  if (!prompt.value.trim()) return
  generating.value = true
  status.value = { status: 'pending', progress: 0 }
  try {
    const payload: VideoGenerationPayload = {
      prompt: prompt.value,
      model: model.value === 'auto' ? undefined : model.value,
      duration: duration.value,
      resolution: resolution.value,
    }
    const refs = [...refImages.value]
    // R2 两段式：无参考图时先生成一张静帧，
    // 以服务端本地产物路径作首帧 → i2v（protocols 本地路径转 data URL 已实测）
    if (staticFirst.value && !refs.length) {
      status.value = { status: 'static-frame', progress: 5 }
      const frameRes: any = await generateImage({ prompt: prompt.value.trim(), width: 1024, height: 1024 })
      const frame = (frameRes?.data?.images ?? [])[0]
      if (frame?.path) refs.push(frame.path)
    }
    if (refs.length) payload.ref_images = refs
    // 协议不随请求下发：服务端 derive_generation_protocol 按 模型→服务商 base_url 自适应推导
    const effProvider = providerOf(model.value)
    if (effProvider) payload.provider_id = effProvider
    if (withAudio.value !== null) payload.audio = withAudio.value
    const res: any = await submitVideo(payload)
    const data = res?.data ?? res
    const taskId = data?.task_id ?? data?.id
    status.value = { status: data?.status ?? 'processing', progress: data?.progress ?? 0 }
    if (taskId) pollStatus(taskId)
  } catch {
    message.error(t('aigc.generateError'))
    generating.value = false
  }
}

function pollStatus(taskId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const res: any = await request.get(`/generation/video/status/${taskId}`)
      const data = res?.data ?? res
      status.value = {
        status: data?.status ?? 'processing',
        progress: data?.status === 'succeeded' ? 100 : status.value?.progress ?? 0,
        url: data?.url,
      }
      if (data?.status === 'succeeded' || data?.status === 'failed') {
        clearInterval(pollTimer!)
        pollTimer = null
        generating.value = false
        if (data.status === 'succeeded') message.success(t('aigc.videoSuccess'))
        else message.error(t('aigc.videoFailed'))
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
  <div class="aigc-video-page">
    <div class="aigc-gen-layout">
      <GlassPanel class="aigc-input-panel" variant="subtle">
        <a-form layout="vertical">
          <a-form-item :label="t('aigc.prompt')">
            <a-textarea v-model:value="prompt" :rows="4" :placeholder="t('aigc.videoPromptPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.model')">
            <a-select v-model:value="model" class="model-select-video" :options="videoModelOptions" :placeholder="t('aigc.selectModel')" show-search />
            <div class="aigc-derived-hint">
              <template v-if="derived">
                <a-tag color="blue">{{ t('aigc.protocol') }}: {{ derived.protocol }}</a-tag>
                <a-tag v-if="derived.providerId">{{ t('aigc.providerId') }}: {{ derived.providerId }}</a-tag>
              </template>
              <span v-else-if="model === 'auto'">{{ t('aigc.protocolAuto') }}</span>
            </div>
          </a-form-item>
          <a-form-item :label="t('aigc.duration')">
            <a-input-number v-model:value="duration" :min="1" :max="60" style="width: 100%" />
          </a-form-item>
          <a-form-item :label="t('aigc.resolution')">
            <a-select v-model:value="resolution">
              <a-select-option value="480p">480p</a-select-option>
              <a-select-option value="720p">720p</a-select-option>
              <a-select-option value="1080p">1080p</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item :label="t('aigc.refImage')">
            <a-upload :show-upload-list="false" accept="image/*" :custom-request="(o: any) => onRefUpload(o.file)">
              <GlassButton size="sm">{{ t('common.upload') }}</GlassButton>
            </a-upload>
            <div v-if="refImages.length" class="aigc-ref-chips">
              <span v-for="(p, i) in refImages" :key="i" class="aigc-ref-chip">
                {{ refFileName(p) }}<button class="aigc-ref-chip-x" type="button" @click="refImages.splice(i, 1)">✕</button>
              </span>
            </div>
          </a-form-item>
          <a-form-item :label="t('aigc.audio')">
            <a-select v-model:value="withAudio" allow-clear :placeholder="t('aigc.protocolAuto')">
              <a-select-option :value="true">{{ t('common.yes') }}</a-select-option>
              <a-select-option :value="false">{{ t('common.no') }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item :label="t('aigc.staticFirst')">
            <a-switch v-model:checked="staticFirst" />
            <div class="aigc-hint">{{ t('aigc.staticFirstHint') }}</div>
          </a-form-item>
          <GlassButton variant="primary" :loading="generating" @click="generate">
            {{ t('aigc.generate') }}
          </GlassButton>
        </a-form>
      </GlassPanel>
      <div>
        <GlassCard :title="t('aigc.videoStatus')" class="aigc-result-panel">
          <div v-if="status" class="aigc-video-status">
            <a-descriptions :column="1" bordered size="small">
              <a-descriptions-item :label="t('aigc.status')">{{ status.status }}</a-descriptions-item>
              <a-descriptions-item :label="t('aigc.progress')">{{ status.progress ?? 0 }}%</a-descriptions-item>
              <a-descriptions-item v-if="status.url" :label="t('aigc.videoUrl')">
                <a :href="withFileToken(status.url)" target="_blank">{{ status.url }}</a>
              </a-descriptions-item>
            </a-descriptions>
            <a-progress :percent="status.progress ?? 0" :status="status.status === 'failed' ? 'exception' : 'active'" />
            <div v-if="status.url && status.status === 'succeeded'">
              <video controls :src="withFileToken(status.url)" style="width: 100%; border-radius: 10px" />
              <a :href="withFileToken(status.url)" :download="status.url.split('/').pop()" class="aigc-download">{{ t('aigc.download') }}</a>
            </div>
          </div>
          <a-empty v-else :description="t('aigc.noVideo')" />
        </GlassCard>
        <AigcHistoryList kind="video" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.aigc-video-status {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
