<script setup lang="ts">
/**
 * 创作专区 · 项目工作台（R4/R5，对标 huobao-drama 四 Phase + 左侧进度导轨）。
 *
 * Phase01 剧情创作：小说→LLM 分集（可手改）；Phase02 场景角色：资产抽取/定妆
 * 图（稳定 seed 一致性，可上传参考图）；Phase03 AI 工作台：分镜拆解 + @角色
 * mention 注入 + 批量首帧/图生视频（账本关联、恢复循环收口）+ 单镜重试；
 * Phase04 制片导出：FFmpeg 合并成片或连播清单播放器。
 * 长任务经 runs 轮询（waitStudioRun），视频进度经 GET episode 账本投影自动刷新。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  addStoryboardManually, getEpisode, getProject,
  runAssetImages, runExtract, runGenerateImages, runGenerateVideos,
  runNarration, runSplitScript, runStoryboards,
  retryStoryboard, updateAsset, updateEpisode, updateStoryboard,
  type ProjectDetail, type StudioEpisode, type StudioStoryboard,
} from '@/api/modules/studio'
import { waitStudioRun } from '@/composables/useStudioRun'
import { useAigcModels } from '@/composables/useAigcModels'
import { uploadFile } from '@/api/modules/files'
import { withFileToken } from '@/utils/genFiles'
import MentionTextarea from '@/components/aigc/MentionTextarea.vue'
import SlideshowPlayer from '@/components/aigc/SlideshowPlayer.vue'
import type { SlideshowItem } from '@/components/aigc/types'
import { mergeEpisode, type MergeResult } from '@/api/modules/studio'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const pid = String(route.params.pid || '')
const { textModelOptions } = useAigcModels()

type Phase = 'script' | 'assets' | 'workbench' | 'export'
const PHASES: { key: Phase; labelKey: string }[] = [
  { key: 'script', labelKey: 'studio.phaseScript' },
  { key: 'assets', labelKey: 'studio.phaseAssets' },
  { key: 'workbench', labelKey: 'studio.phaseWorkbench' },
  { key: 'export', labelKey: 'studio.phaseExport' },
]
const phase = ref<Phase>('script')

const detail = ref<ProjectDetail | null>(null)
const novel = ref('')
const scriptModel = ref('auto')
const currentEid = ref('')
const busy = ref<Record<string, boolean>>({})
const mergeResult = ref<MergeResult | null>(null)
let videoRefreshTimer: ReturnType<typeof setInterval> | null = null

const episodes = computed(() => detail.value?.episodes ?? [])
const characters = computed(() => detail.value?.characters ?? [])
const currentEpisode = computed(
  () => episodes.value.find((e) => e.id === currentEid.value) ?? null)

async function loadDetail() {
  try {
    const res: any = await getProject(pid)
    detail.value = (res?.data ?? null) as ProjectDetail
    if (!currentEid.value && detail.value?.episodes?.length) {
      currentEid.value = detail.value.episodes[0].id
    }
  } catch {
    message.error(t('aigc.generateError'))
  }
}

async function track(kind: string, runId: string) {
  busy.value = { ...busy.value, [kind]: true }
  try {
    const run = await waitStudioRun(pid, runId)
    if (!run) message.error(t('studio.runTimeout'))
    else if (run.status === 'failed') message.error(run.error || t('aigc.generateError'))
    else message.success(t('studio.runDone'))
  } finally {
    busy.value = { ...busy.value, [kind]: false }
    await loadDetail()
  }
}

// ── Phase01 剧情创作 ─────────────────────────────────────────────────────
async function splitScript() {
  if (!novel.value.trim()) return
  const res: any = await runSplitScript(
    pid, novel.value.trim(), scriptModel.value === 'auto' ? undefined : scriptModel.value)
  await track('script', res?.data?.run_id || '')
}

async function saveEpisode(ep: StudioEpisode) {
  await updateEpisode(ep.id, { title: ep.title, content: ep.content })
  message.success(t('studio.saved'))
}

// ── Phase02 场景角色 ─────────────────────────────────────────────────────
async function extractAssets() {
  if (!currentEid.value) return
  const res: any = await runExtract(currentEid.value)
  await track('extract', res?.data?.run_id || '')
}

async function batchAssetImages(ids?: string[]) {
  const res: any = await runAssetImages(pid, { provider: 'ark', ids })
  await track('assetImages', res?.data?.run_id || '')
}

async function uploadAssetImage(c: { id: string; image_path?: string }) {
  try {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const fd = new FormData()
      fd.append('file', file, file.name)
      const up: any = await uploadFile(fd)
      const path = up?.data?.path || up?.path
      if (!path) return
      await updateAsset('characters', c.id, { image_path: path })
      await loadDetail()
    }
    input.click()
  } catch {
    message.error(t('aigc.generateError'))
  }
}

// ── Phase03 AI 工作台 ────────────────────────────────────────────────────
const storyboards = ref<StudioStoryboard[]>([])

async function loadStoryboards() {
  if (!currentEid.value) { storyboards.value = []; return }
  try {
    const res: any = await getEpisode(currentEid.value)
    storyboards.value = res?.data?.storyboards ?? []
    ensureVideoRefresh()
  } catch { storyboards.value = [] }
}

/** 任一镜头视频 running → 5s 自动刷新（账本投影回填） */
function ensureVideoRefresh() {
  const running = storyboards.value.some((s) => s.video_status === 'running')
  if (running && !videoRefreshTimer) {
    videoRefreshTimer = setInterval(() => { void loadStoryboards() }, 5000)
  } else if (!running && videoRefreshTimer) {
    clearInterval(videoRefreshTimer)
    videoRefreshTimer = null
  }
}

async function breakStoryboards(force = false) {
  if (!currentEid.value) return
  const res: any = await runStoryboards(currentEid.value, force)
  await track('storyboards', res?.data?.run_id || '')
  await loadStoryboards()
}

async function addManualShot() {
  if (!currentEid.value) return
  await addStoryboardManually(currentEid.value, { description: '（新镜头，填写画面提示词）', image_prompt: '' })
  await loadStoryboards()
}

/** A1：镜头尾帧（先画后动）——上传落盘后写入 end_frame_path */
function fileNameOf(p?: string): string {
  return (p || '').split(/[\\/]/).pop() || ''
}
function fileUrlOf(p?: string): string {
  return p ? withFileToken(`/api/v1/generation/files/${fileNameOf(p)}`) : ''
}

async function applyShotEndFrame(sb: StudioStoryboard, path: string) {
  await updateStoryboard(sb.id, { end_frame_path: path })
  await loadStoryboards()
}

function setShotEndFrame(sb: StudioStoryboard) {
  try {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const fd = new FormData()
      fd.append('file', file, file.name)
      const up: any = await uploadFile(fd)
      const path = up?.data?.path || up?.path
      if (path) await applyShotEndFrame(sb, path)
    }
    input.click()
  } catch {
    message.error(t('aigc.generateError'))
  }
}

async function saveShot(sb: StudioStoryboard, refs?: { name: string; id: string }[]) {
  await updateStoryboard(sb.id, {
    image_prompt: sb.image_prompt,
    video_prompt: sb.video_prompt,
    narration: sb.narration,
    camera: sb.camera,
    movement: sb.movement,
    duration: sb.duration,
    ...(refs ? { characters: refs } : {}),
  })
  message.success(t('studio.saved'))
}

async function genImages() {
  if (!currentEid.value) return
  const res: any = await runGenerateImages(currentEid.value, { provider: 'ark' })
  await track('images', res?.data?.run_id || '')
  await loadStoryboards()
}

async function genVideos() {
  if (!currentEid.value) return
  const res: any = await runGenerateVideos(currentEid.value, { provider: 'wan', resolution: '720p' })
  await track('videos', res?.data?.run_id || '')
  await loadStoryboards()
}

async function genNarration() {
  if (!currentEid.value) return
  const res: any = await runNarration(currentEid.value)
  await track('narration', res?.data?.run_id || '')
  await loadStoryboards()
}

async function retryShot(sb: StudioStoryboard, stage: 'image' | 'video') {
  await retryStoryboard(sb.id, { stage, provider: stage === 'image' ? 'ark' : 'wan' })
  message.success(t('studio.retryStarted'))
  setTimeout(() => { void loadStoryboards() }, 3000)
}

const mentionCandidates = computed(() =>
  characters.value.map((c) => ({ name: c.name, id: c.id })))

// ── Phase04 制片导出 ─────────────────────────────────────────────────────
async function doMerge() {
  if (!currentEid.value) return
  try {
    const res: any = await mergeEpisode(currentEid.value)
    mergeResult.value = res?.data ?? null
    if (res?.code === -1) message.error(res?.data?.error || t('aigc.generateError'))
  } catch {
    message.error(t('aigc.generateError'))
  }
}

const slideshowItems = computed<SlideshowItem[]>(() => {
  const items = mergeResult.value?.items ?? []
  return items.map((it) => ({
    shot: it.shot,
    url: it.image,
    audio: it.audio,
    description: it.text,
    narration: it.text,
  }))
})

const composedUrl = computed(() => mergeResult.value?.url || '')

function switchPhase(p: Phase) {
  phase.value = p
  if (p === 'workbench') void loadStoryboards()
  if (p === 'export') mergeResult.value = null
}

async function switchEpisode(eid: string) {
  currentEid.value = eid
  await loadStoryboards()
}

onMounted(async () => {
  await loadDetail()
  await loadStoryboards()
})
onUnmounted(() => {
  if (videoRefreshTimer) clearInterval(videoRefreshTimer)
})

defineExpose({
  phase, detail, episodes, characters, storyboards, currentEid, busy,
  novel, scriptModel, mergeResult, slideshowItems, composedUrl,
  splitScript, saveEpisode, extractAssets, batchAssetImages, uploadAssetImage,
  breakStoryboards, saveShot, genImages, genVideos, genNarration, retryShot,
  addManualShot, setShotEndFrame, applyShotEndFrame, fileUrlOf,
  doMerge, switchPhase, switchEpisode, loadStoryboards, loadDetail,
})
</script>

<template>
  <div class="studio-project-page">
    <div class="studio-project-head">
      <GlassButton size="sm" @click="router.push('/aigc/studio')">← {{ t('studio.back') }}</GlassButton>
      <h3 v-if="detail?.project" class="studio-project-title">{{ detail.project.title }}</h3>
      <span v-if="detail?.project" class="studio-project-tags">
        <a-tag color="purple">{{ detail.project.genre }}</a-tag>
        <a-tag>{{ detail.project.aspect_ratio }}</a-tag>
        <a-tag color="cyan">{{ detail.project.style }}</a-tag>
      </span>
    </div>

    <div class="studio-body">
      <!-- 左：进度导轨（huobao 式 Phase 导轨，完成态点亮） -->
      <GlassPanel class="studio-rail" variant="subtle">
        <div
          v-for="(p, i) in PHASES" :key="p.key"
          class="studio-rail-step"
          :class="{ active: phase === p.key, done: i < PHASES.findIndex(x => x.key === phase) }"
          @click="switchPhase(p.key)"
        >
          <span class="studio-rail-dot">{{ i + 1 }}</span>
          <span>{{ t(p.labelKey) }}</span>
        </div>
        <div class="studio-rail-eps">
          <div class="studio-rail-eps-label">{{ t('studio.episodes') }}</div>
          <div
            v-for="ep in episodes" :key="ep.id"
            class="studio-rail-ep"
            :class="{ active: currentEid === ep.id }"
            @click="switchEpisode(ep.id)"
          >
            #{{ ep.number }} {{ ep.title }}
            <a-tag v-if="ep.shots_ready" size="small" color="green">{{ ep.shots_ready }}</a-tag>
          </div>
        </div>
      </GlassPanel>

      <!-- 右：当前 Phase 工作区 -->
      <div class="studio-main">
        <!-- Phase 1 剧情创作 -->
        <GlassPanel v-if="phase === 'script'" variant="subtle" class="studio-panel-block">
          <a-form layout="vertical">
            <a-form-item :label="t('studio.novel')">
              <a-textarea v-model:value="novel" :rows="10" :placeholder="t('studio.novelHint')" />
            </a-form-item>
            <a-form-item :label="t('aigc.model')">
              <a-select v-model:value="scriptModel" class="model-select-script" :options="textModelOptions" />
            </a-form-item>
            <GlassButton variant="primary" :loading="busy.script" @click="splitScript">
              {{ t('studio.splitScript') }}
            </GlassButton>
          </a-form>
          <div v-for="ep in episodes" :key="ep.id" class="studio-episode-block">
            <a-input v-model:value="ep.title" class="studio-ep-title" @change="() => {}" />
            <a-textarea v-model:value="ep.content" :rows="4" />
            <GlassButton size="sm" @click="saveEpisode(ep)">{{ t('studio.save') }}</GlassButton>
          </div>
        </GlassPanel>

        <!-- Phase 2 场景角色 -->
        <GlassPanel v-if="phase === 'assets'" variant="subtle" class="studio-panel-block">
          <div class="studio-toolbar">
            <GlassButton :loading="busy.extract" :disabled="!currentEid" @click="extractAssets">
              {{ t('studio.extractAssets') }}
            </GlassButton>
            <GlassButton variant="primary" :loading="busy.assetImages" :disabled="!characters.length" @click="batchAssetImages()">
              {{ t('studio.generateAssetImages') }}
            </GlassButton>
          </div>
          <div class="studio-asset-grid">
            <div v-for="c in characters" :key="c.id" class="studio-asset-card">
              <div class="studio-asset-img">
                <img v-if="c.image_path" :src="withFileToken('/api/v1/generation/files/' + c.image_path.split(/[\\/]/).pop())" :alt="c.name" />
                <div v-else class="studio-asset-placeholder">{{ c.status }}</div>
              </div>
              <div class="studio-asset-name">@{{ c.name }} <a-tag v-if="c.role">{{ c.role }}</a-tag></div>
              <a-input v-model:value="c.appearance" size="small" :placeholder="t('studio.appearance')" />
              <a-textarea v-model:value="c.final_prompt" size="small" :rows="2" placeholder="final prompt" />
              <div class="studio-asset-actions">
                <GlassButton size="sm" :loading="busy.assetImages" @click="batchAssetImages([c.id])">{{ t('aigc.generate') }}</GlassButton>
                <GlassButton size="sm" @click="uploadAssetImage(c)">{{ t('common.upload') }}</GlassButton>
              </div>
            </div>
          </div>
          <a-empty v-if="!characters.length" :description="t('studio.noAssets')" />
        </GlassPanel>

        <!-- Phase 3 AI 工作台 -->
        <GlassPanel v-if="phase === 'workbench'" variant="subtle" class="studio-panel-block">
          <div class="studio-toolbar">
            <GlassButton :loading="busy.storyboards" :disabled="!currentEid" @click="breakStoryboards(false)">
              {{ t('studio.breakStoryboards') }}
            </GlassButton>
            <GlassButton :disabled="!storyboards.length" @click="breakStoryboards(true)">{{ t('studio.rebreak') }}</GlassButton>
            <GlassButton :disabled="!currentEid" @click="addManualShot">+ {{ t('studio.manualShot') }}</GlassButton>
            <GlassButton :loading="busy.images" :disabled="!storyboards.length" @click="genImages">
              {{ t('studio.genFirstFrames') }}
            </GlassButton>
            <GlassButton :loading="busy.videos" :disabled="!storyboards.length" @click="genVideos">
              {{ t('studio.genVideos') }}
            </GlassButton>
            <GlassButton :loading="busy.narration" :disabled="!storyboards.length" @click="genNarration">
              {{ t('studio.genNarration') }}
            </GlassButton>
          </div>
          <div v-for="sb in storyboards" :key="sb.id" class="studio-shot-card">
            <div class="studio-shot-head">
              <span class="studio-shot-no">#{{ sb.number }}</span>
              <a-tag :color="sb.status === 'video_ready' ? 'success' : sb.status === 'failed' ? 'error' : 'default'">
                {{ sb.status }}<template v-if="sb.video_status && sb.video_status !== 'pending'">/video:{{ sb.video_status }}</template>
              </a-tag>
              <span v-if="sb.error" class="studio-shot-error">{{ sb.error }}</span>
            </div>
            <div class="studio-shot-grid">
              <div class="studio-shot-media">
                <img v-if="sb.first_frame_path" :src="fileUrlOf(sb.first_frame_path)" class="studio-shot-img" />
                <video v-else-if="sb.video_path" controls :src="fileUrlOf(sb.video_path)" class="studio-shot-img" />
                <div v-else class="studio-shot-placeholder">{{ t('studio.noFrame') }}</div>
                <!-- A1：尾帧（先画后动；Seedance/VEO 真透传，WAN 不假生效、进账本 ignored_params 橙标） -->
                <div class="studio-shot-lastframe">
                  <img v-if="sb.end_frame_path" :src="fileUrlOf(sb.end_frame_path)" class="studio-shot-thumb" :alt="t('studio.endFrame')" />
                  <GlassButton size="sm" @click="setShotEndFrame(sb)">
                    {{ sb.end_frame_path ? t('studio.replaceEndFrame') : t('studio.setEndFrame') }}
                  </GlassButton>
                </div>
                <div v-if="sb.end_frame_path" class="studio-lf-note">{{ t('studio.endFrameNote') }}</div>
              </div>
              <div class="studio-shot-form">
                <div class="studio-shot-desc">{{ sb.description }}</div>
                <div class="studio-shot-field-label">{{ t('studio.imagePrompt') }} — {{ t('studio.mentionHint') }}</div>
                <MentionTextarea
                  :model-value="sb.image_prompt"
                  :candidates="mentionCandidates"
                  @update:model-value="(v: string) => (sb.image_prompt = v)"
                  @refs="(refs: any[]) => saveShot(sb, refs)"
                />
                <div class="studio-shot-field-label">{{ t('studio.videoPrompt') }}</div>
                <a-textarea v-model:value="sb.video_prompt" :rows="2" />
                <div class="studio-shot-row">
                  <a-input v-model:value="sb.camera" size="small" :placeholder="t('studio.camera')" style="width: 33%" />
                  <a-input v-model:value="sb.movement" size="small" :placeholder="t('studio.movement')" style="width: 33%" />
                  <a-input-number v-model:value="sb.duration" size="small" :min="1" :max="60" style="width: 25%" />
                </div>
                <div class="studio-shot-field-label">{{ t('studio.narration') }}</div>
                <a-textarea v-model:value="sb.narration" :rows="2" />
                <div class="studio-shot-actions">
                  <GlassButton size="sm" @click="saveShot(sb)">{{ t('studio.save') }}</GlassButton>
                  <GlassButton size="sm" :disabled="!sb.image_prompt && !sb.description" @click="retryShot(sb, 'image')">{{ t('studio.retryImage') }}</GlassButton>
                  <GlassButton size="sm" :disabled="!sb.first_frame_path" @click="retryShot(sb, 'video')">{{ t('studio.retryVideo') }}</GlassButton>
                </div>
              </div>
            </div>
          </div>
          <a-empty v-if="!storyboards.length && !busy.storyboards" :description="t('studio.noShots')" />
        </GlassPanel>

        <!-- Phase 4 制片导出 -->
        <GlassPanel v-if="phase === 'export'" variant="subtle" class="studio-panel-block">
          <div class="studio-toolbar">
            <GlassButton variant="primary" :disabled="!currentEid" @click="doMerge">
              {{ t('studio.mergeNow') }}
            </GlassButton>
            <span v-if="mergeResult" class="studio-merge-mode">
              {{ mergeResult.composed ? t('studio.mergedMp4') : t('studio.mergedManifest') }}
            </span>
          </div>
          <div v-if="composedUrl" class="studio-composed">
            <video controls :src="withFileToken(composedUrl)" style="width: 100%; border-radius: 10px" />
            <a :href="withFileToken(composedUrl)" :download="composedUrl.split('/').pop()" class="aigc-download">{{ t('aigc.download') }}</a>
            <!-- A5：无中文字体/烧录失败时诚实标注（无字幕成片照常交付） -->
            <div v-if="mergeResult?.warning" class="studio-merge-warn">{{ mergeResult.warning }}</div>
          </div>
          <SlideshowPlayer v-else-if="slideshowItems.length" :items="slideshowItems" />
          <a-empty v-else :description="t('studio.noExport')" />
        </GlassPanel>
      </div>
    </div>
  </div>
</template>

<style scoped>
.studio-project-page { display: flex; flex-direction: column; gap: 16px; }
.studio-project-head { display: flex; align-items: center; gap: 14px; }
.studio-project-title { margin: 0; font-size: 17px; color: var(--nr-text-primary); }
.studio-project-tags { display: flex; gap: 6px; }
.studio-body { display: grid; grid-template-columns: 200px 1fr; gap: 16px; align-items: start; }
.studio-rail { padding: 12px; position: sticky; top: 0; }
.studio-rail-step {
  display: flex; align-items: center; gap: 8px; padding: 9px 8px;
  border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--nr-text-secondary);
}
.studio-rail-step:hover { background: rgba(125, 125, 125, 0.1); }
.studio-rail-step.active { background: rgba(64, 150, 255, 0.12); color: var(--nr-text-primary); font-weight: 600; }
.studio-rail-step.done .studio-rail-dot { background: #52c41a; color: #fff; }
.studio-rail-dot {
  width: 20px; height: 20px; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center; font-size: 11px;
  background: rgba(125, 125, 125, 0.25); color: inherit;
}
.studio-rail-eps { margin-top: 14px; border-top: 1px solid var(--nr-border, rgba(255,255,255,.08)); padding-top: 10px; }
.studio-rail-eps-label { font-size: 11px; color: var(--nr-text-secondary); margin-bottom: 6px; }
.studio-rail-ep {
  font-size: 12px; padding: 6px 8px; border-radius: 6px; cursor: pointer;
  color: var(--nr-text-secondary); display: flex; gap: 6px; align-items: center;
}
.studio-rail-ep.active { background: rgba(125, 125, 125, 0.15); color: var(--nr-text-primary); }
.studio-main { min-width: 0; }
.studio-panel-block { padding: 16px 20px; }
.studio-toolbar { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }
.studio-episode-block { display: flex; flex-direction: column; gap: 6px; margin-top: 14px; padding-top: 14px; border-top: 1px dashed var(--nr-border, rgba(255,255,255,.1)); }
.studio-ep-title { max-width: 320px; }
.studio-asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.studio-asset-card { display: flex; flex-direction: column; gap: 6px; padding: 10px; border-radius: 10px; border: 1px solid var(--nr-border, rgba(255,255,255,.08)); }
.studio-asset-img { aspect-ratio: 1; border-radius: 8px; overflow: hidden; background: rgba(0,0,0,.25); display: flex; align-items: center; justify-content: center; }
.studio-asset-img img { width: 100%; height: 100%; object-fit: cover; }
.studio-asset-placeholder { font-size: 12px; color: var(--nr-text-secondary); }
.studio-asset-name { font-size: 13px; font-weight: 600; color: var(--nr-text-primary); }
.studio-asset-actions { display: flex; gap: 6px; }
.studio-shot-card { border: 1px solid var(--nr-border, rgba(255,255,255,.08)); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
.studio-shot-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.studio-shot-no { font-weight: 700; color: var(--nr-text-primary); }
.studio-shot-error { font-size: 12px; color: #ff4d4f; }
.studio-shot-grid { display: grid; grid-template-columns: 180px 1fr; gap: 14px; }
.studio-shot-img { width: 100%; border-radius: 8px; }
.studio-shot-lastframe { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.studio-shot-thumb { width: 72px; aspect-ratio: 9/16; object-fit: cover; border-radius: 6px; border: 1px solid var(--nr-border, rgba(255,255,255,.12)); }
.studio-lf-note { font-size: 10px; line-height: 1.4; color: var(--nr-text-secondary, rgba(255,255,255,.55)); margin-top: 4px; }
.studio-shot-placeholder { aspect-ratio: 9/16; max-height: 220px; border-radius: 8px; background: rgba(0,0,0,.25); display: flex; align-items: center; justify-content: center; color: var(--nr-text-secondary); font-size: 12px; }
.studio-shot-form { display: flex; flex-direction: column; gap: 6px; }
.studio-shot-desc { font-size: 13px; color: var(--nr-text-primary); }
.studio-shot-field-label { font-size: 11px; color: var(--nr-text-secondary); margin-top: 4px; }
.studio-shot-row { display: flex; gap: 8px; }
.studio-shot-actions { display: flex; gap: 8px; margin-top: 6px; }
.studio-composed { display: flex; flex-direction: column; gap: 8px; }
.studio-merge-warn { font-size: 12px; color: #d48806; }
.studio-merge-mode { font-size: 12px; color: var(--nr-text-secondary); }
@media (max-width: 900px) { .studio-body { grid-template-columns: 1fr; } .studio-shot-grid { grid-template-columns: 1fr; } }
</style>
