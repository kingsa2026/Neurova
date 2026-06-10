<template>
  <div
    ref="panelRef"
    class="nr-glass-panel"
    :class="[variant, { 'is-hovered': isHovered, 'is-active': isActive, 'is-glowing': glow }]"
    :style="panelStyle"
    @mouseenter="onMouseEnter"
    @mouseleave="onMouseLeave"
    @mousemove="onMouseMove"
    @mousedown="isActive = true"
    @mouseup="isActive = false"
  >
    <!-- SVG Filter for liquid distortion -->
    <svg class="nr-glass-svg" aria-hidden="true">
      <defs>
        <filter :id="filterId" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB">
          <feImage x="0" y="0" width="100%" height="100%" result="DISPLACEMENT_MAP"
            :href="displacementMap" preserveAspectRatio="xMidYMid slice" />
          <feColorMatrix in="DISPLACEMENT_MAP" type="matrix"
            values="0.3 0.3 0.3 0 0  0.3 0.3 0.3 0 0  0.3 0.3 0.3 0 0  0 0 0 1 0" result="EDGE_INTENSITY" />
          <feComponentTransfer in="EDGE_INTENSITY" result="EDGE_MASK">
            <feFuncA type="discrete" :tableValues="`0 ${aberration * 0.04} 1`" />
          </feComponentTransfer>
          <feOffset in="SourceGraphic" dx="0" dy="0" result="CENTER" />
          <feDisplacementMap in="SourceGraphic" in2="DISPLACEMENT_MAP" :scale="displacement"
            xChannelSelector="R" yChannelSelector="B" result="R_DISP" />
          <feColorMatrix in="R_DISP" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="R_CH" />
          <feDisplacementMap in="SourceGraphic" in2="DISPLACEMENT_MAP" :scale="displacement"
            xChannelSelector="R" yChannelSelector="B" result="G_DISP" />
          <feColorMatrix in="G_DISP" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="G_CH" />
          <feDisplacementMap in="SourceGraphic" in2="DISPLACEMENT_MAP" :scale="displacement"
            xChannelSelector="R" yChannelSelector="B" result="B_DISP" />
          <feColorMatrix in="B_DISP" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="B_CH" />
          <feBlend in="G_CH" in2="B_CH" mode="screen" result="GB" />
          <feBlend in="R_CH" in2="GB" mode="screen" result="RGB" />
          <feGaussianBlur in="RGB" :stdDeviation="Math.max(0.1, 0.4 - aberration * 0.08)" result="BLURRED" />
          <feComposite in="BLURRED" in2="EDGE_MASK" operator="in" result="EDGE" />
          <feComponentTransfer in="EDGE_MASK" result="INV_MASK">
            <feFuncA type="table" tableValues="1 0" />
          </feComponentTransfer>
          <feComposite in="CENTER" in2="INV_MASK" operator="in" result="CENTER_CLEAN" />
          <feComposite in="EDGE" in2="CENTER_CLEAN" operator="over" />
        </filter>
      </defs>
    </svg>

    <!-- Backdrop with filter -->
    <div class="nr-glass-backdrop" :style="backdropStyle" />

    <!-- Animated border gradient -->
    <div class="nr-glass-border" :style="borderStyle" />

    <!-- Specular highlight on hover -->
    <transition name="fade">
      <div v-if="isHovered" class="nr-glass-specular" :style="specularStyle" />
    </transition>

    <!-- Inner shimmer line -->
    <div class="nr-glass-shimmer" />

    <!-- Content -->
    <div class="nr-glass-content">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { CSSProperties } from 'vue'

const props = withDefaults(defineProps<{
  variant?: 'default' | 'elevated' | 'subtle' | 'prominent'
  displacement?: number
  blur?: number
  saturation?: number
  aberration?: number
  radius?: number
  padding?: string
  glow?: boolean
  noHover?: boolean
}>(), {
  variant: 'default',
  displacement: 60,
  blur: 12,
  saturation: 180,
  aberration: 2,
  radius: 20,
  padding: '20px 24px',
  glow: false,
  noHover: false,
})

const panelRef = ref<HTMLElement | null>(null)
const isHovered = ref(false)
const isActive = ref(false)
const mouse = ref({ x: 0, y: 0 })
const uid = Math.random().toString(36).slice(2, 8)
const filterId = `nr-glass-${uid}`

const displacementMap = 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAgAAZABkAAD/2wCEAAQDAwMDAwQDAwQGBAMEBgcFBAQFBwgHBwcHBwgLCAkJCQkICwsMDAwMDAsNDQ4ODQ0SEhISEhQUFBQUFBQUFBQBBQUFCAgIEAsLEBQODg4UFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFP/CABEIAQABAAMBEQACEQEDEQH/8QAFgABAQEAAAAAAAAAAAAAAAAABgUEB//EAB8QAAIBBAMBAAAAAAAAAAAAAAECAxEEBSESMUH/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8A'

const variantConfig = computed(() => {
  switch (props.variant) {
    case 'elevated': return { bg: 0.06, bgHover: 0.1, border: 0.12, borderHover: 0.22, shadow: 40 }
    case 'subtle': return { bg: 0.02, bgHover: 0.04, border: 0.05, borderHover: 0.1, shadow: 16 }
    case 'prominent': return { bg: 0.08, bgHover: 0.14, border: 0.18, borderHover: 0.3, shadow: 60 }
    default: return { bg: 0.04, bgHover: 0.07, border: 0.08, borderHover: 0.16, shadow: 28 }
  }
})

const onMouseEnter = () => { if (!props.noHover) isHovered.value = true }
const onMouseLeave = () => { isHovered.value = false; mouse.value = { x: 0, y: 0 } }
const onMouseMove = (e: MouseEvent) => {
  if (!panelRef.value || props.noHover) return
  const r = panelRef.value.getBoundingClientRect()
  mouse.value = { x: ((e.clientX - r.left - r.width / 2) / r.width) * 100, y: ((e.clientY - r.top - r.height / 2) / r.height) * 100 }
}

const panelStyle = computed<CSSProperties>(() => ({
  position: 'relative',
  overflow: 'hidden',
  borderRadius: `${props.radius}px`,
  transition: 'all 0.4s cubic-bezier(0.22, 1, 0.36, 1)',
  transform: isActive.value ? 'scale(0.985)' : isHovered.value ? 'translateY(-4px) scale(1.005)' : 'none',
  ...(props.glow && { boxShadow: '0 0 40px rgba(99,102,241,0.15), 0 0 80px rgba(99,102,241,0.08)' }),
}))

const backdropStyle = computed<CSSProperties>(() => ({
  position: 'absolute', inset: 0, zIndex: 0,
  filter: `url(#${filterId})`,
  backdropFilter: `blur(${props.blur}px) saturate(${props.saturation}%)`,
  WebkitBackdropFilter: `blur(${props.blur}px) saturate(${props.saturation}%)`,
  background: `
    radial-gradient(ellipse 120% 80% at ${30 + mouse.value.x * 0.2}% ${10 + mouse.value.y * 0.15}%, rgba(99,102,241,${isHovered.value ? 0.12 : 0.06}) 0%, transparent 60%),
    radial-gradient(ellipse 80% 60% at ${70 - mouse.value.x * 0.15}% ${30 + mouse.value.y * 0.1}%, rgba(34,211,238,${isHovered.value ? 0.08 : 0.04}) 0%, transparent 50%),
    linear-gradient(145deg, rgba(255,255,255,${variantConfig.value.bg}) 0%, rgba(255,255,255,${variantConfig.value.bg * 0.4}) 50%, rgba(255,255,255,${variantConfig.value.bg * 0.7}) 100%)
  `,
  transition: 'background 0.5s ease',
}))

const borderStyle = computed<CSSProperties>(() => {
  const angle = 135 + mouse.value.x * 1.5
  const o1 = variantConfig.value.border + Math.abs(mouse.value.x) * 0.003
  const o2 = (isHovered.value ? variantConfig.value.borderHover : variantConfig.value.border) + Math.abs(mouse.value.y) * 0.004
  const p1 = Math.max(10, 30 + mouse.value.y * 0.3)
  const p2 = Math.min(90, 65 + mouse.value.y * 0.4)
  return {
    position: 'absolute', inset: 0, zIndex: 2, pointerEvents: 'none',
    borderRadius: `${props.radius}px`,
    padding: '1px',
    WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    WebkitMaskComposite: 'xor', maskComposite: 'exclude',
    background: `linear-gradient(${angle}deg, transparent 0%, rgba(255,255,255,${o1}) ${p1}%, rgba(255,255,255,${o2}) ${p2}%, transparent 100%)`,
    boxShadow: `inset 0 0.5px 0 rgba(255,255,255,0.15), inset 0 -0.5px 0 rgba(255,255,255,0.05), 0 ${variantConfig.value.shadow}px ${variantConfig.value.shadow * 2}px rgba(0,0,0,${isHovered.value ? 0.4 : 0.25})`,
    transition: 'box-shadow 0.4s ease',
  }
})

const specularStyle = computed<CSSProperties>(() => ({
  position: 'absolute', inset: 0, zIndex: 3, pointerEvents: 'none',
  borderRadius: `${props.radius}px`,
  background: `radial-gradient(ellipse 60% 40% at ${50 + mouse.value.x * 0.5}% ${20 + mouse.value.y * 0.3}%, rgba(255,255,255,0.12) 0%, transparent 60%)`,
  mixBlendMode: 'overlay',
}))
</script>

<style scoped>
.nr-glass-panel { display: block; }
.nr-glass-svg { position: absolute; width: 0; height: 0; overflow: hidden; }
.nr-glass-backdrop { transition: background 0.5s ease; }
.nr-glass-border { transition: all 0.4s ease; }
.nr-glass-specular { transition: opacity 0.3s ease; }
.nr-glass-shimmer {
  position: absolute; inset: 0; z-index: 1; pointer-events: none;
  border-radius: inherit;
  background: linear-gradient(105deg, transparent 40%, rgba(255,255,255,0.03) 45%, rgba(255,255,255,0.06) 50%, rgba(255,255,255,0.03) 55%, transparent 60%);
  animation: shimmer 8s ease-in-out infinite;
}
@keyframes shimmer {
  0%, 100% { transform: translateX(-100%); }
  50% { transform: translateX(100%); }
}
.nr-glass-content {
  position: relative; z-index: 4;
  padding: v-bind('props.padding');
  color: var(--nr-text-primary);
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.25s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
