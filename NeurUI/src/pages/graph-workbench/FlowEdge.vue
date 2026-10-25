<template>
  <BaseEdge :id="id" :path="path" :class="['flow-base', $attrs.class as string | undefined]" />
  <path :d="path" class="flow-stream" fill="none" pointer-events="none">
    <title>{{ label ?? '' }}</title>
  </path>
</template>

<script setup lang="ts">
/**
 * 流光边（工作台）：两条 path 叠加——VueFlow 默认边只有一条 path，
 * animated 虚线会整体覆盖底色，做不出『实线底 + 流光层』的双层观感。
 * 底层走 BaseEdge（保留 VueFlow 的边事件/选中语义），流光层是纯装饰
 * path（pointer-events none，不拦截交互）；relation 文本放原生 <title>
 * 悬停提示，不为每条边增挂标签 DOM。
 */
import { computed } from 'vue'
import { BaseEdge, getBezierPath } from '@vue-flow/core'

const props = defineProps<{
  id: string
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
  sourcePosition?: string
  targetPosition?: string
  label?: string
}>()

const path = computed(() =>
  getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    sourcePosition: (props.sourcePosition ?? 'right') as never,
    targetPosition: (props.targetPosition ?? 'left') as never,
  })[0] ?? '',
)
</script>
