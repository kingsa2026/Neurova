import { ref, computed, onMounted, onUnmounted, watch, type CSSProperties } from 'vue'
export interface LiquidGlassProps {
  displacementScale?: number
  blurAmount?: number
  saturation?: number
  aberrationIntensity?: number
  elasticity?: number
  cornerRadius?: number
  className?: string
  padding?: string
  style?: CSSProperties
  mode?: 'standard' | 'polar' | 'prominent'
}
const displacementMaps = {
  standard: 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAgAAZABkAAD/2wCEAAQDAwMDAwQDAwQGBAMEBgcFBAQFBwgHBwcHBwgLCAkJCQkICwsMDAwMDAsNDQ4ODQ0SEhISEhQUFBQUFBQUFBQBBQUFCAgIEAsLEBQODg4UFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFP/CABEIAQABAAMBEQACEQEDEQH/8QAFgABAQEAAAAAAAAAAAAAAAAABgUEB//EACMQAAIBBAICAwAAAAAAAAAAAAECAAMEESESMUFRYf/EABUBAQEAAAAAAAAAAAAAAAAAAAID/8QAGhEAAgMBAQAAAAAAAAAAAAAAAAECEQMSIf/aAAwDAQACEQMRAD8A',
  polar: 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAgAAZABkAAD/2wCEAAQDAwMDAwQDAwQGBAMEBgcFBAQFBwgHBwcHBwgLCAkJCQkICwsMDAwMDAsNDQ4ODQ0SEhISEhQUFBQUFBQUFBQBBQUFCAgIEAsLEBQODg4UFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFP/CABEIAQABAAMBEQACEQEDEQH/8QAFgABAQEAAAAAAAAAAAAAAAAABgUEB//EAB8QAAIBBAMBAAAAAAAAAAAAAAECAxEEBSESMUH/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8A',
}
export default function useLiquidGlass(props: LiquidGlassProps = {}) {
  const glassRef = ref&lt;HTMLElement | null&gt;(null)
  const isHovered = ref(false)
  const isActive = ref(false)
  const glassSize = ref({ width: 270, height: 69 })
  const mouseOffset = ref({ x: 0, y: 0 })
  const displacementScale = computed(() =&gt; props.displacementScale ?? 70)
  const blurAmount = computed(() =&gt; props.blurAmount ?? 0.0625)
  const saturation = computed(() =&gt; props.saturation ?? 140)
  const aberrationIntensity = computed(() =&gt; props.aberrationIntensity ?? 2)
  const elasticity = computed(() =&gt; props.elasticity ?? 0.15)
  const cornerRadius = computed(() =&gt; props.cornerRadius ?? 999)
  const mode = computed(() =&gt; props.mode ?? 'standard')
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
    mouseOffset.value = { x: 0, y: 0 }
  }
  const handleMouseDown = () =&gt; {
    isActive.value = true
  }
  const handleMouseUp = () =&gt; {
    isActive.value = false
  }
  const updateGlassSize = () =&gt; {
    if (glassRef.value) {
      const rect = glassRef.value.getBoundingClientRect()
      glassSize.value = { width: rect.width, height: rect.height }
    }
  }
  onMounted(() =&gt; {
    updateGlassSize()
    window.addEventListener('resize', updateGlassSize)
  })
  onUnmounted(() =&gt; {
    window.removeEventListener('resize', updateGlassSize)
  })
  watch(glassRef, (el) =&gt; {
    if (el) {
      el.addEventListener('mouseenter', handleMouseEnter)
      el.addEventListener('mouseleave', handleMouseLeave)
      el.addEventListener('mousemove', handleMouseMove)
      el.addEventListener('mousedown', handleMouseDown)
      el.addEventListener('mouseup', handleMouseUp)
    }
  })
  const containerStyle = computed&lt;CSSProperties&gt;(() =&gt; ({
    position: 'relative',
    display: 'inline-flex',
    alignItems: 'center',
    gap: '24px',
    padding: props.padding ?? '24px 32px',
    overflow: 'hidden',
    transition: 'all 0.2s ease-in-out',
    borderRadius: `${cornerRadius.value}px`,
    boxShadow: '0px 12px 40px rgba(0, 0, 0, 0.25)',
    ...props.style,
  }))
  const backdropStyle = computed&lt;CSSProperties&gt;(() =&gt; ({
    filter: `url(#glass-${mode.value})`,
    backdropFilter: `blur(${4 + blurAmount.value * 32}px) saturate(${saturation.value}%)`,
  }))
  const borderStyle = computed&lt;CSSProperties&gt;(() =&gt; {
    const gradientAngle = 135 + mouseOffset.value.x * 1.2
    const opacity1 = 0.12 + Math.abs(mouseOffset.value.x) * 0.008
    const opacity2 = 0.4 + Math.abs(mouseOffset.value.x) * 0.012
    const position1 = Math.max(10, 33 + mouseOffset.value.y * 0.3)
    const position2 = Math.min(90, 66 + mouseOffset.value.y * 0.4)
    return {
      position: 'absolute',
      inset: 0,
      borderRadius: `${cornerRadius.value}px`,
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
  const hoverEffectStyle = computed&lt;CSSProperties&gt;(() =&gt; ({
    position: 'absolute',
    inset: 0,
    borderRadius: `${cornerRadius.value}px`,
    pointerEvents: 'none',
    transition: 'all 0.2s ease-out',
    opacity: isHovered.value || isActive.value ? 0.5 : 0,
    backgroundImage: 'radial-gradient(circle at 50% 0%, rgba(255, 255, 255, 0.5) 0%, rgba(255, 255, 255, 0) 50%)',
    mixBlendMode: 'overlay',
  }))
  const filterId = `glass-${mode.value}`
  return {
    glassRef,
    containerStyle,
    backdropStyle,
    borderStyle,
    hoverEffectStyle,
    isHovered,
    isActive,
    glassSize,
    mouseOffset,
    filterId,
    displacementScale,
    aberrationIntensity,
  }
}
&nbsp;