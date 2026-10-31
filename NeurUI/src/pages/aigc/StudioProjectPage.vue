<script setup lang="ts">
/**
 * 创作专区 · 项目工作台。
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
  addStoryboardManually, cancelStudioRun, getEpisode, getProject,
  runAssetImages, runExtract, runGenerateImages, runGenerateVideos,
  runNarration, runSplitScript, runStoryboards,
  retryStoryboard, updateAsset, updateEpisode, updateStoryboard,
  getMerge, type ProjectDetail, type StudioEpisode,
  type StudioRun, type StudioStoryboard,
} from '@/api/modules/studio'
import { waitStudioRun, describeRunOutcome, parseRunDetail } from '@/composables/useStudioRun'
import { useAigcModels } from '@/composables/useAigcModels'
import { uploadFile } from '@/api/modules/files'
import { withFileToken } from '@/utils/genFiles'
import MentionTextarea from '@/components/aigc/MentionTextarea.vue'
import SlideshowPlayer from '@/components/aigc/SlideshowPlayer.vue'
import type { SlideshowItem } from '@/components/aigc/types'
import { mergeEpisode, type MergeResult } from '@/api/modules/studio'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { basenameOf } from '@/utils/pathText'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const pid = String(route.params.pid || '')
const { textModelOptions, imageModelOptions, videoModelOptions, providerOf } = useAigcModels()

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
const imgModel = ref('auto')
const vdModel = ref('auto')
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

/** 在跑的长任务：kind → run_id。停止按钮取的就是这一格，收尾即摘。 */
const activeRuns = ref<Record<string, string>>({})
const stoppingRun = ref(false)
// 并发跑两类长任务是允许的（各按钮的 busy 键不同）：按钮必须把**全部**在跑的停掉，
// 而不是取第一条——那等于"点了停没反应"（§6-91 未覆盖面④）。
const activeRunIds = computed(() => Object.values(activeRuns.value))
const runningCount = computed(() => activeRunIds.value.length)

async function track(kind: string, runId: string): Promise<StudioRun | null> {
  busy.value = { ...busy.value, [kind]: true }
  activeRuns.value = { ...activeRuns.value, [kind]: runId }
  let run: StudioRun | null = null
  try {
    run = await waitStudioRun(pid, runId)
    if (!run) message.error(t('studio.runTimeout'))
    else if (run.status === 'failed') message.error(run.error || t('aigc.generateError'))
    else if (run.status === 'cancelled') message.info(run.error || t('studio.runCancelled'))
    else if (run.status === 'done_with_fallback') {
      // 带病完成不能报「任务完成」：条数与成因由结算侧写进 detail_json，这里取用（§6-87）
      message.warning(t('studio.runPartial', { detail: describeRunOutcome(run, t) }))
    } else message.success(t('studio.runDone'))
    return run
  } finally {
    busy.value = { ...busy.value, [kind]: false }
    const rest = { ...activeRuns.value }
    delete rest[kind]
    activeRuns.value = rest
    await loadDetail()
  }
}

/**
 * 停止当前长任务（取消四件套的前端那一件）。
 *
 * 两个读数分开播报：`tasks_cancelled > 0` 才是"本进程的句柄真被打断"；只有意图落库时
 * （服务重启过、句柄不在）说"已停止"就是把没发生的事说成发生了，那条只报"已请求停止，
 * 剩余步骤不再续跑"。后端点名过的原因（404 归属/不存在、409 已终态）必须透出，
 * 只说"失败了"没法定位。
 */
async function cancelActiveRun() {
  const runIds = activeRunIds.value
  if (!runIds.length || stoppingRun.value) return
  stoppingRun.value = true
  try {
    const results = await Promise.allSettled(runIds.map((rid) => cancelStudioRun(rid)))
    const interrupted = results.filter(
      (r) => r.status === 'fulfilled' && Number((r.value as any)?.data?.tasks_cancelled) > 0).length
    if (interrupted > 0) message.success(t('studio.runCancelled'))
    else message.info(t('studio.runCancelQueued'))
    const failed = results.find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined
    if (failed) message.error(failed.reason?.response?.data?.detail || t('aigc.generateError'))
  } finally {
    stoppingRun.value = false
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
  const res: any = await runAssetImages(pid, { ...imgParams(), ids })
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
  if (!currentEid.value) { storyboards.value = []; ensureVideoRefresh(); return }
  try {
    const res: any = await getEpisode(currentEid.value)
    storyboards.value = res?.data?.storyboards ?? []
  } catch { storyboards.value = [] }
  // 成败都要重判启停：失败分支只清空列表不停表，5s 表就会无限打 GET（§6-78 F 条①）
  ensureVideoRefresh()
}

/** 定时器唯一的停表口（`videoRefreshTimer` 只在这一处被清） */
function stopVideoRefresh() {
  if (videoRefreshTimer) {
    clearInterval(videoRefreshTimer)
    videoRefreshTimer = null
  }
}

/** 任一镜头视频 running → 5s 自动刷新（账本投影回填）；启停同一个入口判同一份状态 */
function ensureVideoRefresh() {
  const running = storyboards.value.some((s) => s.video_status === 'running')
  if (!running) { stopVideoRefresh(); return }
  if (!videoRefreshTimer) {
    videoRefreshTimer = setInterval(() => { void loadStoryboards() }, 5000)
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
  await addStoryboardManually(currentEid.value, { description: t('aigc.newShotPlaceholder'), image_prompt: '' })
  await loadStoryboards()
}

/** A1：镜头尾帧（先画后动）——上传落盘后写入 end_frame_path */
function fileUrlOf(p?: string): string {
  return p ? withFileToken(`/api/v1/generation/files/${basenameOf(p)}`) : ''
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

/** 选定模型 → 请求参数（auto=不传，后端按能力路由；选中项反查 provider_id） */
function imgParams(): { model?: string; provider_id?: string } {
  if (!imgModel.value || imgModel.value === 'auto') return {}
  return { model: imgModel.value, provider_id: providerOf(imgModel.value) || undefined }
}
function vdParams(): { model?: string; provider_id?: string } {
  if (!vdModel.value || vdModel.value === 'auto') return {}
  return { model: vdModel.value, provider_id: providerOf(vdModel.value) || undefined }
}

async function genImages() {
  if (!currentEid.value) return
  const res: any = await runGenerateImages(currentEid.value, imgParams())
  await track('images', res?.data?.run_id || '')
  await loadStoryboards()
}

async function genVideos() {
  if (!currentEid.value) return
  const res: any = await runGenerateVideos(currentEid.value, { ...vdParams(), resolution: '720p' })
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
  const res: any = await retryStoryboard(sb.id, { stage, ...(stage === 'image' ? imgParams() : vdParams()) })
  message.success(t('studio.retryStarted'))
  // 与其它长任务同一个入口：等 run 收口后再读镜头面。改前是发一次 setTimeout(3000)——
  // 提交落在服务端后台任务里，3s 时读到的常是旧态，running 永不成立、周期表根本不启（§6-78 F 条③）
  await track(`retry_${stage}`, res?.data?.run_id || '')
  await loadStoryboards()
}

const mentionCandidates = computed(() =>
  characters.value.map((c) => ({ name: c.name, id: c.id })))

// ── Phase04 制片导出 ─────────────────────────────────────────────────────
/** A3：用户提供的 BGM 乐轨（上传落盘后混音；AI 生成 BGM 无实测服务商不支持） */
const bgmPath = ref('')
async function uploadBgm() {
  try {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'audio/*'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const fd = new FormData()
      fd.append('file', file, file.name)
      const up: any = await uploadFile(fd)
      const path = up?.data?.path || up?.path
      if (path) bgmPath.value = path
    }
    input.click()
  } catch {
    message.error(t('aigc.generateError'))
  }
}

async function doMerge() {
  if (!currentEid.value) return
  try {
    const accepted: any = await mergeEpisode(currentEid.value,
      bgmPath.value ? { bgm_path: bgmPath.value } : undefined)
    const runId = accepted?.data?.run_id
    if (!runId) {
      message.error(t('aigc.generateError'))
      return
    }
    // 导出现在是后台 run：能停（顶部停止按钮覆盖所有在跑的 kind）、能查（runs 投影）。
    // 产物明细仍以 `merges` 表为唯一事实源，所以 poll 到终态后再取那一行，
    // 不把 items 塞进 detail_json 造成第二份表示。
    const run = await track('merge', runId)
    if (!run || run.status === 'failed' || run.status === 'cancelled') return
    const detail = parseRunDetail(run)
    const mid = String(detail.merge_id || '')
    if (!mid) return
    const row = (await getMerge(mid))?.data?.merge
    if (!row) return
    mergeResult.value = {
      ok: true,
      composed: Boolean(detail.composed),
      mode: String(detail.mode || row.mode || ''),
      url: String(detail.url || ''),
      subtitle_burned: Boolean(detail.subtitle_burned),
      bgm_mixed: Boolean(detail.bgm_mixed),
      warning: String(detail.fallback || ''),
      merge: row,
      items: JSON.parse(row.items_json || '[]'),
    }
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
  // 离开工作台时镜头卡片已被 v-if 摘掉，表却还在后台每 5s 拉一次整集（§6-78 F 条②）
  else stopVideoRefresh()
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
  stopVideoRefresh()
})

defineExpose({
  phase, detail, episodes, characters, storyboards, currentEid, busy,
  activeRuns, activeRunIds, runningCount, stoppingRun, cancelActiveRun, track,
  novel, scriptModel, imgModel, vdModel, mergeResult, slideshowItems, composedUrl,
  splitScript, saveEpisode, extractAssets, batchAssetImages, uploadAssetImage,
  breakStoryboards, saveShot, genImages, genVideos, genNarration, retryShot,
  imgParams, vdParams,
  addManualShot, setShotEndFrame, applyShotEndFrame, fileUrlOf,
  bgmPath, uploadBgm,
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
      <!-- 长任务的停止入口：只在有任务在跑时出现（条件是 activeRuns 非空，而不是 phase 匹配
           ——拆解/批量出图/旁白任一步都要能停，按钮常驻但点了没用比看不见入口更糟）。
           多条并发时如实报条数：一次点击停掉全部，不让用户猜"停的是哪一条"。 -->
      <GlassButton v-if="runningCount" size="sm" :loading="stoppingRun" @click="cancelActiveRun">
        {{ runningCount > 1 ? t('studio.stopRunN', { n: runningCount }) : t('studio.stopRun') }}
      </GlassButton>
    </div>

    <div class="studio-body">
      <!-- 左：进度导轨 -->
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
            <a-select v-model:value="imgModel" class="model-select-script" :options="imageModelOptions" size="small" style="min-width: 180px" />
          </div>
          <div class="studio-asset-grid">
            <div v-for="c in characters" :key="c.id" class="studio-asset-card">
              <div class="studio-asset-img">
                <img v-if="c.image_path" :src="withFileToken('/api/v1/generation/files/' + basenameOf(c.image_path))" :alt="c.name" />
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
            <a-select v-model:value="imgModel" class="model-select-script" :options="imageModelOptions" size="small" style="min-width: 180px" />
            <GlassButton :loading="busy.videos" :disabled="!storyboards.length" @click="genVideos">
              {{ t('studio.genVideos') }}
            </GlassButton>
            <a-select v-model:value="vdModel" class="model-select-script" :options="videoModelOptions" size="small" style="min-width: 180px" />
            <GlassButton :loading="busy.narration" :disabled="!storyboards.length" @click="genNarration">
              {{ t('studio.genNarration') }}
            </GlassButton>
          </div>
          <div v-for="sb in storyboards" :key="sb.id" class="studio-shot-card">
            <div class="studio-shot-head">
              <span class="studio-shot-no">#{{ sb.number }}</span>
              <span v-if="sb.title" class="studio-shot-no">{{ sb.title }}</span>
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
                <!-- 首帧生成时 @角色/道具/场景被注入后的成品提示词（services.py 唯一写点）：
                     回看它才知道模型实际收到什么，改前这列写了没人读。 -->
                <div v-if="sb.injected_prompt" class="studio-shot-injected">
                  <div class="studio-shot-field-label">{{ t('studio.injectedPrompt') }}</div>
                  <div class="studio-shot-injected-text">{{ sb.injected_prompt }}</div>
                </div>
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
            <GlassButton size="sm" @click="uploadBgm">
              {{ bgmPath ? t('studio.replaceBgm') : t('studio.uploadBgm') }}
            </GlassButton>
            <span v-if="bgmPath" class="studio-merge-mode">{{ basenameOf(bgmPath) }}</span>
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
.studio-rail-step.done .studio-rail-dot { background: var(--nr-success); color: #fff; }
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
.studio-shot-error { font-size: 12px; color: var(--nr-error); flex: 1; min-width: 0; word-break: break-word; }
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
.studio-merge-warn { font-size: 12px; color: var(--nr-warning); }
.studio-merge-mode { font-size: 12px; color: var(--nr-text-secondary); }
@media (max-width: 900px) { .studio-body { grid-template-columns: 1fr; } .studio-shot-grid { grid-template-columns: 1fr; } }
</style>
