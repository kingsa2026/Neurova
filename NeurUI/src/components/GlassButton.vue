<template>
  <button
    ref="btnRef"
    class="nr-glass-btn"
    :class="[`nr-glass-btn--${variant}`, `nr-glass-btn--${size}`, { 'is-loading': loading, 'is-disabled': disabled }]"
    :disabled="disabled || loading"
    @mouseenter="isHovered = true"
    @mouseleave="isHovered = false; mouse = { x: 0, y: 0 }"
    @mousemove="onMouse"
    @click="$emit('click', $event)"
  >
    <span class="nr-glass-btn-bg" :style="bgStyle" />
    <span class="nr-glass-btn-shine" :style="shineStyle" />
    <span class="nr-glass-btn-content">
      <span v-if="loading" class="nr-glass-btn-spinner">
        <svg viewBox="0 0 24 24" width="16" height="16"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2.5" stroke-dasharray="31.4 31.4" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/></circle></svg>
      </span>
      <span v-if="icon && !loading" class="nr-glass-btn-icon"><component :is="icon" /></span>
      <span v-if="$slots.default" class="nr-glass-btn-label"><slot /></span>
    </span>
  </button>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { CSSProperties } from 'vue'

const props = withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  icon?: object
  loading?: boolean
  disabled?: boolean
}>(), {
  variant: 'secondary',
  size: 'md',
  loading: false,
  disabled: false,
})

defineEmits<{ click: [e: MouseEvent] }>()

const btnRef = ref<HTMLElement | null>(null)
const isHovered = ref(false)
const mouse = ref({ x: 0, y: 0 })

const onMouse = (e: MouseEvent) => {
  if (!btnRef.value) return
  const r = btnRef.value.getBoundingClientRect()
  mouse.value = { x: ((e.clientX - r.left) / r.width) * 100, y: ((e.clientY - r.top) / r.height) * 100 }
}

const bgStyle = computed<CSSProperties>(() => ({
  opacity: isHovered.value ? 1 : 0.8,
}))

const shineStyle = computed<CSSProperties>(() => ({
  background: isHovered.value
    ? `radial-gradient(circle 80px at ${mouse.value.x}% ${mouse.value.y}%, rgba(255,255,255,0.2) 0%, transparent 60%)`
    : 'none',
}))
</script>

<style scoped>
.nr-glass-btn {
  position: relative; display: inline-flex; align-items: center; justify-content: center;
  border: none; cursor: pointer; overflow: hidden;
  border-radius: 12px; font-family: var(--nr-font-body);
  font-weight: 500; letter-spacing: -0.01em;
  transition: all 0.3s cubic-bezier(0.22, 1, 0.36, 1);
  outline: none;
}
.nr-glass-btn--sm { height: 32px; padding: 0 14px; font-size: 12px; border-radius: 8px; gap: 6px; }
.nr-glass-btn--md { height: 40px; padding: 0 20px; font-size: 13px; border-radius: 12px; gap: 8px; }
.nr-glass-btn--lg { height: 48px; padding: 0 28px; font-size: 15px; border-radius: 14px; gap: 10px; }

.nr-glass-btn--primary .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a78bfa 100%);
  transition: opacity 0.3s;
}
.nr-glass-btn--primary { color: white; box-shadow: 0 4px 20px rgba(99,102,241,0.3), inset 0 1px 0 rgba(255,255,255,0.15); }
.nr-glass-btn--primary:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(99,102,241,0.4), inset 0 1px 0 rgba(255,255,255,0.2); }

.nr-glass-btn--secondary .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: rgba(255,255,255,0.06); backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid rgba(255,255,255,0.1); border-radius: inherit;
  transition: all 0.3s;
}
.nr-glass-btn--secondary { color: var(--nr-text-primary); }
.nr-glass-btn--secondary:hover .nr-glass-btn-bg { background: rgba(255,255,255,0.1); border-color: rgba(255,255,255,0.18); }
.nr-glass-btn--secondary:hover { transform: translateY(-1px); }

.nr-glass-btn--ghost .nr-glass-btn-bg {
  position: absolute; inset: 0; background: transparent; border-radius: inherit; transition: all 0.3s;
}
.nr-glass-btn--ghost { color: var(--nr-text-secondary); }
.nr-glass-btn--ghost:hover { color: var(--nr-text-primary); }
.nr-glass-btn--ghost:hover .nr-glass-btn-bg { background: rgba(255,255,255,0.04); }

.nr-glass-btn--danger .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: linear-gradient(135deg, #ef4444, #dc2626);
  border-radius: inherit; transition: opacity 0.3s;
}
.nr-glass-btn--danger { color: white; box-shadow: 0 4px 20px rgba(239,68,68,0.3); }
.nr-glass-btn--danger:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(239,68,68,0.4); }

.nr-glass-btn-shine { position: absolute; inset: 0; z-index: 1; pointer-events: none; transition: background 0.2s; }
.nr-glass-btn-content { position: relative; z-index: 2; display: flex; align-items: center; gap: inherit; }
.nr-glass-btn-spinner { display: flex; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.nr-glass-btn-icon { display: flex; font-size: 1.1em; }
.nr-glass-btn-label { white-space: nowrap; }

.nr-glass-btn.is-loading { opacity: 0.8; pointer-events: none; }
.nr-glass-btn.is-disabled { opacity: 0.4; pointer-events: none; cursor: not-allowed; }
.nr-glass-btn:active:not(.is-disabled):not(.is-loading) { transform: scale(0.97); }
</style>
