<template>
  <div
    class="nr-dock-resizer"
    :title="t('dock.resizeHint')"
    @mousedown.prevent="onMouseDown"
    @dblclick="onReset"
  />
  <!-- 拖拽期透明遮罩：盖住 dock 全域（含 iframe），防 iframe 吞 mousemove -->
  <div v-if="isResizing" class="nr-dock-resizer-overlay" />
</template>

<script setup lang="ts">
/**
 * Dock 左缘拖拽调宽手柄（浏览器 DevTools 分栏惯例）。
 *
 * 关键坑位：内容区的 sandbox iframe 在 mousemove 冒泡路径上会截获指针
 * 事件导致拖拽中断——拖拽期间渲染一层全 dock 透明 overlay 压住 iframe
 * （z-index 高于内容），mouseup 后移除。
 */
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  width: number
  min?: number
  max?: number
}>()

const emit = defineEmits<{
  resize: [width: number]
  reset: []
}>()

const { t } = useI18n()

const isResizing = ref(false)
let startX = 0
let startWidth = 0

function clamp(w: number): number {
  const min = props.min ?? 320
  const max = Math.max(props.max ?? 9999, min)
  return Math.min(Math.max(w, min), max)
}

function onMouseMove(e: MouseEvent): void {
  // dock 在右侧：向左拖（dx 负）→ 宽度增加
  const dx = e.clientX - startX
  emit('resize', clamp(startWidth - dx))
}

function onMouseUp(): void {
  isResizing.value = false
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

function onMouseDown(e: MouseEvent): void {
  startX = e.clientX
  startWidth = props.width
  isResizing.value = true
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

function onReset(): void {
  emit('reset')
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})
</script>

<style scoped>
.nr-dock-resizer {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 7px;
  cursor: col-resize;
  z-index: 12;
}
.nr-dock-resizer:hover {
  background: var(--nr-primary-soft, rgba(99, 102, 241, 0.25));
}
.nr-dock-resizer-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  cursor: col-resize;
}
</style>
