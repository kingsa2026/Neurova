<template>
  <div ref="glassRef" class="liquid-glass-wrapper" :class="className" :style="wrapperStyle">
    <svg :style="{ position: 'absolute', width: glassSize.width, height: glassSize.height }" aria-hidden="true">
      <defs>
        <filter id="glass-standard" x="-35%" y="-35%" width="170%" height="170%" color-interpolation-filters="sRGB">
          <feImage x="0" y="0" width="100%" height="100%" result="DISPLACEMENT_MAP" href="data:image/jpeg;base64,/9j/4AAQSkZJRgABAgAAZABkAAD/2wCEAAQDAwMDAwQDAwQGBAMEBgcFBAQFBwgHBwcHBwgLCAkJCQkICwsMDAwMDAsNDQ4ODQ0SEhISEhQUFBQUFBQUFBQBBQUFCAgIEAsLEBQODg4UFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFP/CABEIAQABAAMBEQACEQEDEQH/8QAFgABAQEAAAAAAAAAAAAAAAAABgUEB//EAB8QAAIBBAMBAAAAAAAAAAAAAAECAxEEBSESMUH/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8A" preserveAspectRatio="xMidYMid slice" />
          <feColorMatrix in="DISPLACEMENT_MAP" type="matrix" values="0.3 0.3 0.3 0 0 0.3 0.3 0.3 0 0 0.3 0.3 0.3 0 0 0 0 0 1 0" result="EDGE_INTENSITY" />
          <feComponentTransfer in="EDGE_INTENSITY" result="EDGE_MASK">
            <feFuncA type="discrete" :tableValues="`0 ${aberrationIntensity * 0.05} 1`" />
          </feComponentTransfer>
          <feOffset in="SourceGraphic" dx="0" dy="0" result="CENTER_ORIGINAL" />
          <feDisplacementMap in="SourceGraphic" in2="DISPLACEMENT_MAP" :scale="displacementScale" xChannelSelector="R" yChannelSelector="B" result="RED_DISPLACED" />
          <feColorMatrix in="RED_DISPLACED" type="matrix" values="1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0" result="RED_CHANNEL" />
          <feDisplacementMap in="SourceGraphic" in2="DISPLACEMENT_MAP" :scale="displacementScale" xChannelSelector="R" yChannelSelector="B" result="GREEN_DISPLACED" />
          <feColorMatrix in="GREEN_DISPLACED" type="matrix" values="0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 1 0" result="GREEN_CHANNEL" />
          <feDisplacementMap in="SourceGraphic" in2="DISPLACEMENT_MAP" :scale="displacementScale" xChannelSelector="R" yChannelSelector="B" result="BLUE_DISPLACED" />
          <feColorMatrix in="BLUE_DISPLACED" type="matrix" values="0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 1 0" result="BLUE_CHANNEL" />
          <feBlend in="GREEN_CHANNEL" in2="BLUE_CHANNEL" mode="screen" result="GB_COMBINED" />
          <feBlend in="RED_CHANNEL" in2="GB_COMBINED" mode="screen" result="RGB_COMBINED" />
          <feGaussianBlur in="RGB_COMBINED" :stdDeviation="Math.max(0.1, 0.5 - aberrationIntensity * 0.1)" result="ABERRATED_BLURRED" />
          <feComposite in="ABERRATED_BLURRED" in2="EDGE_MASK" operator="in" result="EDGE_ABERRATION" />
          <feComponentTransfer in="EDGE_MASK" result="INVERTED_MASK">
            <feFuncA type="table" tableValues="1 0" />
          </feComponentTransfer>
          <feComposite in="CENTER_ORIGINAL" in2="INVERTED_MASK" operator="in" result="CENTER_CLEAN" />
          <feComposite in="EDGE_ABERRATION" in2="CENTER_CLEAN" operator="over" />
        </filter>
      </defs>
    </svg>

    <div class="glass-content" :style="containerStyle">
      <span class="glass-backdrop" :style="backdropStyle" />

      <div class="glass-border" :style="borderStyle" />

      <div v-if="isHovered || isActive" class="glass-hover-effect" :style="hoverEffectStyle" />

      <div class="glass-children">
        <slot />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CSSProperties } from 'vue'

export interface LiquidGlassComponentProps {
  displacementScale?: number
  blurAmount?: number
  saturation?: number
  aberrationIntensity?: number
  elasticity?: number
  cornerRadius?: number
  className?: string
  padding?: string
  style?: CSSProperties
}

const props = withDefaults(defineProps<LiquidGlassComponentProps>(), {
  displacementScale: 70,
  blurAmount: 0.0625,
  saturation: 140,
  aberrationIntensity: 2,
  elasticity: 0.15,
  cornerRadius: 28,
  className: '',
  padding: '24px 32px',
})

const glassRef = ref<HTMLElement | null>(null)
const isHovered = ref(false)
const isActive = ref(false)
const glassSize = ref({ width: 360, height: 200 })
const mouseOffset = ref({ x: 0, y: 0 })

const handleMouseMove = (e: MouseEvent) => {
  if (!glassRef.value) return
  const rect = glassRef.value.getBoundingClientRect()
  const centerX = rect.left + rect.width / 2
  const centerY = rect.top + rect.height / 2
  mouseOffset.value = {
    x: ((e.clientX - centerX) / rect.width) * 100,
    y: ((e.clientY - centerY) / rect.height) * 100,
  }
}

const containerStyle = computed<CSSProperties>(() => ({
  position: 'relative',
  display: 'flex',
  flexDirection: 'column',
  gap: '14px',
  padding: '22px',
  overflow: 'hidden',
  transition: 'all 0.45s cubic-bezier(0.4,0,0.2,1)',
  borderRadius: `${props.cornerRadius}px`,
  boxShadow: '0 8px 32px rgba(0,0,0,0.25), 0 2px 8px rgba(0,0,0,0.1), inset 0 0 0 0.5px rgba(255,255,255,0.12), inset 0 1px 0 rgba(255,255,255,0.18)',
  background: `
    radial-gradient(120px 80px at 20% 0%, rgba(139,92,246,0.12) 0%, transparent 100%),
    radial-gradient(90px 60px at 90% 20%, rgba(99,102,241,0.08) 0%, transparent 100%),
    linear-gradient(145deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.03) 50%, rgba(255,255,255,0.06) 100%)
  `,
  backdropFilter: 'blur(40px) saturate(180%)',
  WebkitBackdropFilter: 'blur(40px) saturate(180%)',
  ...(isHovered.value && {
    transform: 'translateY(-6px) scale(1.01)',
    boxShadow: '0 20px 48px rgba(0,0,0,0.35), 0 8px 16px rgba(0,0,0,0.18), inset 0 0 0 0.5px rgba(255,255,255,0.18), inset 0 1px 0 rgba(255,255,255,0.25)',
    background: `
      radial-gradient(140px 100px at 20% 0%, rgba(139,92,246,0.18) 0%, transparent 100%),
      radial-gradient(110px 80px at 90% 20%, rgba(99,102,241,0.14) 0%, transparent 100%),
      linear-gradient(145deg, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0.09) 100%)
    `,
  }),
}))

const backdropStyle = computed<CSSProperties>(() => ({
  filter: 'url(#glass-standard)',
  backdropFilter: `blur(${4 + props.blurAmount * 32}px) saturate(${props.saturation}%)`,
  position: 'absolute',
  inset: 0,
}))

const borderStyle = computed<CSSProperties>(() => {
  const gradientAngle = 135 + mouseOffset.value.x * 1.2
  const opacity1 = 0.12 + Math.abs(mouseOffset.value.x) * 0.008
  const opacity2 = 0.4 + Math.abs(mouseOffset.value.x) * 0.012
  const position1 = Math.max(10, 33 + mouseOffset.value.y * 0.3)
  const position2 = Math.min(90, 66 + mouseOffset.value.y * 0.4)

  return {
    position: 'absolute',
    inset: 0,
    borderRadius: `${props.cornerRadius}px`,
    pointerEvents: 'none',
    mixBlendMode: 'screen',
    opacity: 0.2,
    padding: '1.5px',
    WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    WebkitMaskComposite: 'xor',
    maskComposite: 'exclude',
    boxShadow: '0 0 0 0.5px rgba(255, 255, 255, 0.5) inset, 0 1px 3px rgba(255, 255, 255, 0.25) inset, 0 1px 4px rgba(0, 0, 0, 0.35)',
    background: `linear-gradient(${gradientAngle}deg, rgba(255, 255, 255, 0.0) 0%, rgba(255, 255, 255, ${opacity1}) ${position1}%, rgba(255, 255, 255, ${opacity2}) ${position2}%, rgba(255, 255, 255, 0.0) 100%)`,
  }
})

const hoverEffectStyle = computed<CSSProperties>(() => ({
  position: 'absolute',
  inset: 0,
  borderRadius: `${props.cornerRadius}px`,
  pointerEvents: 'none',
  transition: 'all 0.2s ease-out',
  opacity: isHovered.value || isActive.value ? 0.5 : 0,
  backgroundImage: 'radial-gradient(circle at 50% 0%, rgba(255, 255, 255, 0.5) 0%, rgba(255, 255, 255, 0) 50%)',
  mixBlendMode: 'overlay',
}))

const wrapperStyle = computed<CSSProperties>(() => ({
  position: 'relative',
  ...props.style,
}))

defineExpose({
  glassRef,
  isHovered,
  isActive,
})

onMounted(() => {
  if (glassRef.value) {
    glassRef.value.addEventListener('mouseenter', () => { isHovered.value = true })
    glassRef.value.addEventListener('mouseleave', () => { isHovered.value = false; mouseOffset.value = { x: 0, y: 0 } })
    glassRef.value.addEventListener('mousemove', handleMouseMove)
    glassRef.value.addEventListener('mousedown', () => { isActive.value = true })
    glassRef.value.addEventListener('mouseup', () => { isActive.value = false })
  }
})
</script>

<style scoped>
.liquid-glass-wrapper {
  display: inline-block;
}

.glass-content {
  position: relative;
}

.glass-backdrop {
  z-index: 0;
}

.glass-border {
  z-index: 2;
}

.glass-hover-effect {
  z-index: 3;
}

.glass-children {
  position: relative;
  z-index: 1;
  color: white;
  text-shadow: 0px 2px 12px rgba(0, 0, 0, 0.4);
}
</style>
