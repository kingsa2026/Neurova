<script setup lang="ts">
/**
 * MiniMap.vue — 画布小地图（遗留 F）
 *
 * 纯渲染：布局计算在 canvasMinimap.ts（纯函数，已单测）。
 * 点击 mini → emit pan-to（父组件设 viewport.panX/panY）。
 */
import { computed } from 'vue'
import {
  computeMinimapLayout,
  miniClickToPan,
  type MinimapNodeLike,
  type MinimapViewport,
} from './canvasMinimap'

const props = defineProps<{
  nodes: MinimapNodeLike[]
  viewport: MinimapViewport
  container: { w: number; h: number }
}>()

const emit = defineEmits<{
  (e: 'pan-to', pan: { panX: number; panY: number }): void
}>()

const MINI = { w: 180, h: 120 }

const layout = computed(() =>
  computeMinimapLayout(props.nodes, props.viewport, props.container, MINI),
)

function handleClick(e: MouseEvent) {
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const click = { x: e.clientX - rect.left, y: e.clientY - rect.top }
  emit('pan-to', miniClickToPan(click, layout.value, props.container))
}
</script>

<template>
  <div
    class="canvas-minimap"
    data-testid="canvas-minimap"
    @mousedown.stop
    @click="handleClick"
  >
    <svg :width="MINI.w" :height="MINI.h">
      <rect
        v-for="m in layout.nodeRects"
        :key="m.id"
        :x="m.x"
        :y="m.y"
        :width="Math.max(m.w, 4)"
        :height="Math.max(m.h, 3)"
        rx="2"
        class="mini-node"
      />
      <rect
        :x="layout.viewportRect.x"
        :y="layout.viewportRect.y"
        :width="layout.viewportRect.w"
        :height="layout.viewportRect.h"
        class="mini-viewport"
      />
    </svg>
  </div>
</template>

<style scoped>
.canvas-minimap {
  position: absolute;
  right: 12px;
  bottom: 12px;
  width: 180px;
  height: 120px;
  background: var(--nr-bg-elevated, rgba(15, 20, 35, 0.92));
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.1));
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  z-index: 50;
}
.mini-node {
  fill: var(--nr-primary-light, #818cf8);
  opacity: 0.75;
}
.mini-viewport {
  fill: rgba(129, 140, 248, 0.12);
  stroke: var(--nr-primary-light, #818cf8);
  stroke-width: 1.5;
}
</style>