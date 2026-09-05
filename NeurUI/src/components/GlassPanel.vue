<template>
  <div
    ref="panelRef"
    class="nr-glass-panel"
    :class="[variant, { 'is-glowing': glow }]"
    :style="panelStyle"
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

    <!-- Liquid Glass 顶部高光描边（specular rim，仅顶部 1.5px 可见） -->
    <div class="nr-glass-specular" />

    <!-- Content -->
    <div class="nr-glass-content">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
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

const panelStyle = computed<CSSProperties>(() => ({
  position: 'relative',
  overflow: 'hidden',
  borderRadius: `${props.radius}px`,
  ...(props.glow && { boxShadow: '0 0 40px color-mix(in srgb, var(--nr-primary) 15%, transparent), 0 0 80px color-mix(in srgb, var(--nr-primary) 8%, transparent)' }),
}))

const backdropStyle = computed<CSSProperties>(() => ({
  position: 'absolute', inset: 0, zIndex: 0,
  filter: `url(#${filterId})`,
  backdropFilter: `blur(${props.blur}px) saturate(${props.saturation}%)`,
  WebkitBackdropFilter: `blur(${props.blur}px) saturate(${props.saturation}%)`,
  background: `
    radial-gradient(ellipse 70% 42% at 24% 6%, var(--nr-glass-highlight) 0%, transparent 60%),
    radial-gradient(ellipse 120% 80% at 30% 10%, color-mix(in srgb, var(--nr-primary) 6%, transparent) 0%, transparent 60%),
    radial-gradient(ellipse 80% 60% at 70% 30%, color-mix(in srgb, var(--nr-accent) 4%, transparent) 0%, transparent 50%),
    linear-gradient(145deg, rgba(var(--nr-glass-rgb),${variantConfig.value.bg}) 0%, rgba(var(--nr-glass-rgb),${variantConfig.value.bg * 0.4}) 50%, rgba(var(--nr-glass-rgb),${variantConfig.value.bg * 0.7}) 100%)
  `,
}))

const borderStyle = computed<CSSProperties>(() => ({
  position: 'absolute', inset: 0, zIndex: 2, pointerEvents: 'none',
  borderRadius: `${props.radius}px`,
  padding: '1px',
  WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
  WebkitMaskComposite: 'xor', maskComposite: 'exclude',
  background: `linear-gradient(135deg, transparent 0%, rgba(var(--nr-glass-rgb),${variantConfig.value.border}) 30%, rgba(var(--nr-glass-rgb),${variantConfig.value.borderHover}) 65%, transparent 100%)`,
  boxShadow: `inset 0 0.5px 0 rgba(var(--nr-glass-rgb),0.15), inset 0 -0.5px 0 rgba(var(--nr-glass-rgb),0.05), 0 ${variantConfig.value.shadow}px ${variantConfig.value.shadow * 2}px rgba(0,0,0,0.25)`,
}))
</script>

<style scoped>
.nr-glass-panel { display: block; }
.nr-glass-svg { position: absolute; width: 0; height: 0; overflow: hidden; }
.nr-glass-content {
  position: relative; z-index: 4;
  padding: v-bind('props.padding');
  color: var(--nr-text-primary);
}
/* Liquid Glass 顶部高光描边：2.5px 高、中间亮两侧渐隐，
   贴合圆角（border-radius: inherit），cosmic 皮肤自然退化为弱光泽 */
.nr-glass-specular {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
  border-radius: inherit;
  -webkit-mask: linear-gradient(to bottom, #000 0, #000 2.5px, transparent 2.5px);
  mask: linear-gradient(to bottom, #000 0, #000 2.5px, transparent 2.5px);
  background: linear-gradient(90deg,
    transparent 4%,
    var(--nr-glass-specular-top) 15%,
    var(--nr-glass-specular-top) 85%,
    transparent 96%);
  opacity: 0.9;
}
</style>
