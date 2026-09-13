<script setup lang="ts">
/**
 * SlideshowPlayer（批次4）：一键成片的诚实"成片"形态。
 *
 * 无 FFmpeg 环境时 video-compose 输出连播清单 manifest——本组件按镜头播放
 * 画面 + 旁白音频 + 字幕；有 FFmpeg 时模板 compose 节点直接产出 mp4，
 * 本组件同样兼容（audio 项即镜头旁白）。产物 URL 走 withFileToken 鉴权。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { withFileToken } from '@/utils/genFiles'
import type { SlideshowItem } from './types'

const props = defineProps<{ items: SlideshowItem[] }>()

const { t } = useI18n()

const idx = ref(0)
const playing = ref(false)
const audioEl = ref<HTMLAudioElement | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

const current = computed<SlideshowItem | null>(() => props.items[idx.value] ?? null)
const imgSrc = computed(() => {
  const url = current.value?.url || ''
  if (!url) return ''
  return /^https?:\/\//i.test(url) ? url : withFileToken(url)
})
const audioSrc = computed(() => {
  const url = current.value?.audio || ''
  return url ? withFileToken(url) : ''
})

function clearTimer() {
  if (timer) { clearTimeout(timer); timer = null }
}

function schedule() {
  clearTimer()
  if (!playing.value) return
  const item = current.value
  if (item?.audio) {
    // 有旁白：audio ended 事件推进（onAudioEnded）
    return
  }
  timer = setTimeout(advance, 3500)
}

function advance() {
  if (idx.value < props.items.length - 1) {
    idx.value += 1
  } else {
    playing.value = false
    clearTimer()
  }
}

function onAudioEnded() { advance() }

function play() {
  if (!props.items.length) return
  playing.value = true
  void audioEl.value?.play?.()
  schedule()
}

function pause() {
  playing.value = false
  clearTimer()
  audioEl.value?.pause?.()
}

function toggle() { playing.value ? pause() : play() }

function next() {
  clearTimer()
  if (idx.value < props.items.length - 1) idx.value += 1
  if (playing.value) { void audioEl.value?.play?.(); schedule() }
}

function prev() {
  clearTimer()
  if (idx.value > 0) idx.value -= 1
  if (playing.value) { void audioEl.value?.play?.(); schedule() }
}

watch(idx, () => { /* schedule 由 play/next/prev 与 watch playing 驱动 */ })
watch(() => playing.value, (p) => { if (!p) { clearTimer(); audioEl.value?.pause?.() } })

defineExpose({ idx, playing, play, pause, toggle, next, prev })

onBeforeUnmount(() => { clearTimer(); audioEl.value?.pause?.() })
</script>

<template>
  <div class="slideshow">
    <div v-if="!current" class="slideshow-empty">
      <a-empty :description="t('aigc.noResult')" />
    </div>
    <template v-else>
      <div class="slideshow-stage">
        <img v-if="imgSrc" :src="imgSrc" :alt="current.description || t('aigc.studioShot')" />
        <div v-else class="slideshow-placeholder">{{ current.prompt || current.description || '—' }}</div>
        <audio
          v-if="current.audio"
          ref="audioEl"
          :src="audioSrc"
          preload="auto"
          @ended="onAudioEnded"
        />
      </div>
      <div class="slideshow-caption">
        <div class="cap-text">{{ current.description }}</div>
        <div v-if="current.narration" class="cap-narration">{{ current.narration }}</div>
      </div>
      <div class="slideshow-controls">
        <button type="button" :title="t('aigc.studioPrev')" @click="prev">⏮</button>
        <button type="button" class="play-btn" @click="toggle">{{ playing ? '⏸' : '▶' }}</button>
        <button type="button" :title="t('aigc.studioNext')" @click="next">⏭</button>
        <span class="slideshow-idx">{{ t('aigc.studioShot') }} {{ idx + 1 }} / {{ items.length }}</span>
        <span class="slideshow-downloads">
          <a v-if="imgSrc" :href="imgSrc" :download="(current.url || '').split('/').pop()" class="history-download">{{ t('aigc.download') }}</a>
          <a v-if="current.audio" :href="audioSrc" :download="(current.audio || '').split('/').pop()" class="history-download">{{ t('aigc.download') }}</a>
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.slideshow { display: flex; flex-direction: column; gap: 12px; }
.slideshow-stage {
  position: relative;
  aspect-ratio: 9 / 16;
  max-height: 58vh;
  border-radius: 12px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}
.slideshow-stage img { width: 100%; height: 100%; object-fit: contain; }
.slideshow-placeholder { padding: 24px; text-align: center; color: var(--nr-text-secondary); font-size: 13px; }
.slideshow-caption { text-align: center; }
.cap-text { font-size: 14px; color: var(--nr-text-primary); }
.cap-narration { margin-top: 4px; font-size: 13px; color: var(--nr-text-secondary); }
.slideshow-controls { display: flex; align-items: center; gap: 10px; justify-content: center; }
.slideshow-controls button {
  border: none;
  background: rgba(125, 125, 125, 0.15);
  color: var(--nr-text-primary);
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
}
.play-btn { font-size: 15px; }
.slideshow-idx { font-size: 12px; color: var(--nr-text-secondary); }
.slideshow-downloads { display: flex; gap: 8px; margin-left: 8px; }
</style>
