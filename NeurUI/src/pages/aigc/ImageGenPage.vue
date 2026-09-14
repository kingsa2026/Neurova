<script setup lang="ts">
/**
 * AIGC 图片生成页（2026-09-14 R1 拆分；R2 对齐 PRINTFILM 工具表单面）。
 *
 * 契约保持：风格模板内置常量 + 提示词注入（批次1）；参考图上传 →
 * ref_images（批次3）；model=auto 不透传（后端按 image_generation 能力路由）；
 * 产物 URL 带访问凭证；记录侧栏默认过滤 image。
 * R2 新增：反向提示词、画幅 chips、张数、seed、i2i 相似度（低/中/高→strength）、
 * 能力自适应——服务商忽略的参数经 ignored_params 显式提示（不静默丢弃）。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { generateImage as apiGenerateImage } from '@/api/modules/generation'
import { uploadFile } from '@/api/modules/files'
import { useAigcModels } from '@/composables/useAigcModels'
import { withFileToken } from '@/utils/genFiles'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import AigcHistoryList from '@/components/aigc/AigcHistoryList.vue'

const { t } = useI18n()
const { imageModelOptions } = useAigcModels()

// 画幅 chips（PRINTFILM ratio 语义）→ 后端 width/height
const RATIO_SIZE: Record<string, [number, number]> = {
  '1:1': [1024, 1024],
  '16:9': [1280, 720],
  '9:16': [720, 1280],
}
// 相似度 chips（PRINTFILM i2i strength 低/中/高）
const STRENGTH_VALUES: Record<string, number> = { low: 0.35, mid: 0.65, high: 0.9 }

// 内置风格模板（非 Docker 模板接口，批次1 决策保持）
const STYLE_TEMPLATES: { value: string; hint: string }[] = [
  { value: 'default', hint: '' },
  { value: 'photorealistic', hint: 'photorealistic, ultra-detailed, 8k' },
  { value: 'anime', hint: 'anime style, vibrant colors, clean lineart' },
  { value: 'oil-painting', hint: 'oil painting style, visible textured brush strokes' },
]
const TEMPLATE_LABEL_KEYS: Record<string, string> = {
  default: 'default',
  photorealistic: 'photorealistic',
  anime: 'anime',
  'oil-painting': 'oilPainting',
}
const templateOptions = computed(() =>
  STYLE_TEMPLATES.map((tpl) => ({ label: t(`aigc.${TEMPLATE_LABEL_KEYS[tpl.value]}`), value: tpl.value })))

const prompt = ref('')
const negativePrompt = ref('')
const ratio = ref('1:1')
const strengthLevel = ref('mid')
const numImages = ref(1)
const seed = ref<number | null>(null)
const template = ref('default')
const model = ref('auto')
const generating = ref(false)
const results = ref<{ url: string; prompt: string }[]>([])
const previewVisible = ref(false)
const previewUrl = ref('')
const refImages = ref<string[]>([])

async function onRefUpload(file: File) {
  try {
    const fd = new FormData()
    fd.append('file', file, (file as any).name || 'ref.png')
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
  try {
    const tpl = STYLE_TEMPLATES.find((x) => x.value === template.value)
    const styledPrompt = tpl?.hint ? `${prompt.value.trim()}\n${tpl.hint}` : prompt.value.trim()
    const [width, height] = RATIO_SIZE[ratio.value] ?? [1024, 1024]
    const res: any = await apiGenerateImage({
      prompt: styledPrompt,
      negative_prompt: negativePrompt.value.trim() || undefined,
      model: model.value === 'auto' ? undefined : model.value,
      width,
      height,
      num_images: Math.max(1, Math.min(4, numImages.value || 1)),
      seed: seed.value ?? undefined,
      // 相似度仅在图生图（有参考图）时下发；三协议暂不支持会进 ignored_params
      strength: refImages.value.length ? STRENGTH_VALUES[strengthLevel.value] : undefined,
      ref_images: refImages.value.length ? [...refImages.value] : undefined,
    })
    const data = res?.data ?? res
    if (data?.ignored_params) {
      message.info(t('aigc.ignoredParams', { params: String(data.ignored_params) }))
    }
    const rawImages: any[] = data?.images ?? data?.urls ?? (data?.url ? [data.url] : [])
    const urls: string[] = rawImages
      .map((i: any) => (typeof i === 'string' ? i : i?.url))
      .filter(Boolean)
    for (const url of urls) {
      results.value.unshift({ url, prompt: prompt.value })
    }
    message.success(t('aigc.imageSuccess'))
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    generating.value = false
  }
}

function preview(img: { url: string }) {
  previewUrl.value = img.url
  previewVisible.value = true
}
</script>

<template>
  <div class="aigc-image-page">
    <div class="aigc-gen-layout">
      <GlassPanel class="aigc-input-panel" variant="subtle">
        <a-form layout="vertical">
          <a-form-item :label="t('aigc.prompt')">
            <a-textarea v-model:value="prompt" :rows="3" :placeholder="t('aigc.imagePromptPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.negative')">
            <a-textarea v-model:value="negativePrompt" :rows="2" :placeholder="t('aigc.negativePlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.ratio')">
            <a-radio-group v-model:value="ratio" size="small">
              <a-radio-button v-for="r in ['1:1', '16:9', '9:16']" :key="r" :value="r">{{ r }}</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item :label="t('aigc.template')">
            <a-select v-model:value="template" :options="templateOptions" :placeholder="t('aigc.selectTemplate')" show-search />
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
          <a-form-item v-if="refImages.length" :label="t('aigc.strength')">
            <a-radio-group v-model:value="strengthLevel" size="small">
              <a-radio-button value="low">{{ t('aigc.strengthLow') }}</a-radio-button>
              <a-radio-button value="mid">{{ t('aigc.strengthMid') }}</a-radio-button>
              <a-radio-button value="high">{{ t('aigc.strengthHigh') }}</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item :label="t('aigc.numImages')">
            <a-input-number v-model:value="numImages" :min="1" :max="4" style="width: 100%" />
          </a-form-item>
          <a-form-item :label="t('aigc.seed')">
            <a-input-number v-model:value="seed" :min="0" style="width: 100%" :placeholder="t('aigc.seedPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('aigc.model')">
            <a-select v-model:value="model" class="model-select-image" :options="imageModelOptions" :placeholder="t('aigc.selectModel')" show-search />
          </a-form-item>
          <GlassButton variant="primary" :loading="generating" @click="generate">
            {{ t('aigc.generate') }}
          </GlassButton>
        </a-form>
      </GlassPanel>
      <div>
        <GlassCard :title="t('aigc.gallery')" class="aigc-result-panel">
          <div v-if="results.length" class="aigc-image-gallery">
            <div v-for="(img, idx) in results" :key="idx" class="aigc-gallery-item" @click="preview(img)">
              <img :src="withFileToken(img.url)" :alt="img.prompt" />
            </div>
          </div>
          <a-empty v-else :description="t('aigc.noImages')" />
        </GlassCard>
        <AigcHistoryList kind="image" />
      </div>
    </div>

    <a-modal v-model:open="previewVisible" :footer="null" width="680px">
      <img :src="withFileToken(previewUrl)" alt="Preview" style="width: 100%" />
    </a-modal>
  </div>
</template>
