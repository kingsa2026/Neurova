&lt;template&gt;
  &lt;div
    ref="glassRef"
    :
    :style="containerStyle"
    @mousemove="handleMouseMove"
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
    @mousedown="handleMouseDown"
    @mouseup="handleMouseUp"
    @click="onClick"
  &gt;
    &lt;slot /&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
  onClick?: () =&gt; void
}
const props = withDefaults(defineProps&lt;Props&gt;(), {
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
const glassRef = ref&lt;HTMLElement | null&gt;(null)
const isHovered = ref(false)
const isActive = ref(false)
const mouseOffset = ref({ x: 0, y: 0 })
const getBackground = () =&gt; {
  if (props.overLight) {
    return 'rgba(255, 255, 255, 0.25)'
  }
  return 'rgba(255, 255, 255, 0.08)'
}
const getBoxShadow = () =&gt; {
  const intensity = isHovered.value ? 0.3 : 0.15
  const spread = isActive.value ? 8 : 20
  return `0 ${spread}px 40px rgba(0,0,0,${intensity}), 0 0 0 0.5px rgba(255,255,255,0.1)`
}
const containerStyle = computed&lt;CSSProperties&gt;(() =&gt; ({
  position: 'relative' as const,
  padding: props.padding,
  borderRadius: `${props.cornerRadius}px`,
  background: getBackground(),
  border: '1px solid rgba(255,255,255,0.12)',
  boxShadow: getBoxShadow(),
  backdropFilter: `blur(${4 + props.blurAmount * 32}px) saturate(${props.saturation}%)`,
  WebkitBackdropFilter: `blur(${4 + props.blurAmount * 32}px) saturate(${props.saturation}%)`,
  transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
}))
const handleMouseMove = (e: MouseEvent) =&gt; {
  if (!glassRef.value) return
  const rect = glassRef.value.getBoundingClientRect()
  const centerX = rect.left + rect.width / 2
  const centerY = rect.top + rect.height / 2
  mouseOffset.value = {
    x: ((e.clientX - centerX) / rect.width) * 100,
    y: ((e.clientY - centerY) / rect.height) * 100,
  }
}
const handleMouseEnter = () =&gt; {
  isHovered.value = true
}
const handleMouseLeave = () =&gt; {
  isHovered.value = false
  isActive.value = false
}
const handleMouseDown = () =&gt; {
  isActive.value = true
}
const handleMouseUp = () =&gt; {
  isActive.value = false
}
onMounted(() =&gt; {
  // Component ready
})
onUnmounted(() =&gt; {
  // Cleanup
})
&lt;/script&gt;
&lt;style scoped&gt;
.glass-effect {
  will-change: transform, backdrop-filter;
}
&lt;/style&gt;
&nbsp;