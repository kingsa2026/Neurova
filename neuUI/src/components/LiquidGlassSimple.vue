<template>
  <div
    ref="glassRef"
    :class="['glass-effect', className]"
    :style="containerStyle"
    @mousemove="handleMouseMove"
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
    @mousedown="handleMouseDown"
    @mouseup="handleMouseUp"
    @click="onClick"
  >
    <slot />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, type CSSProperties } from 'vue'

interface Props {
  displacementScale?: number
  blurAmount?: number
  saturation?: number
  aberrationIntensity?: number
  elasticity?: number
  cornerRadius?: number
  className?: string
  padding?: string
  style?: CSSProperties
  overLight?: boolean
  mode?: 'standard' | 'polar' | 'prominent'
  onClick?: () => void
}

const props = withDefaults(defineProps<Props>(), {
  displacementScale: 70,
  blurAmount: 0.0625,
  saturation: 150,
  aberrationIntensity: 2,
  elasticity: 0.15,
  cornerRadius: 28,
  className: '',
  padding: '22px',
  overLight: false,
  mode: 'standard',
})

const emit = defineEmits(['click'])

const glassRef = ref<HTMLElement | null>(null)
const isHovered = ref(false)
const isActive = ref(false)
const mouseOffset = ref({ x: 0, y: 0 })

const containerStyle = computed<CSSProperties>(() => ({
  position: 'relative' as const,
  padding: props.padding,
  borderRadius: `${props.cornerRadius}px`,
  background: getBackground(),
  border: '1px solid rgba(255,255,255,0.12)',
  boxShadow: getBoxShadow(),
  backdropFilter: `blur(${4 + props.blurAmount * 32}