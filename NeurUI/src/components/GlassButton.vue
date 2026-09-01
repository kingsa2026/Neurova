<template>
  <button
    ref="btnRef"
    class="nr-glass-btn"
    :class="[`nr-glass-btn--${variant}`, `nr-glass-btn--${size}`, { 'is-loading': loading, 'is-disabled': disabled }]"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <span class="nr-glass-btn-bg" />
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
import { ref } from 'vue'

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
  background: var(--nr-gradient-primary);
  transition: opacity 0.3s;
}
.nr-glass-btn--primary { color: white; box-shadow: 0 4px 20px color-mix(in srgb, var(--nr-primary) 30%, transparent), inset 0 1px 0 rgba(255,255,255,0.15); }

.nr-glass-btn--secondary .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: linear-gradient(135deg, #162d50 0%, #1e4976 50%, #1a3f66 100%);
  border: 1px solid rgba(59, 130, 246, 0.25); border-radius: inherit;
  transition: all 0.3s;
}
.nr-glass-btn--secondary { color: #e0eaff; box-shadow: 0 2px 12px rgba(30, 64, 120, 0.25), inset 0 1px 0 rgba(255,255,255,0.08); }
.nr-glass-btn--secondary:hover .nr-glass-btn-bg { background: linear-gradient(135deg, #1e3d6b 0%, #2563a0 50%, #1f5080 100%); border-color: rgba(59, 130, 246, 0.4); }
.nr-glass-btn--secondary:hover { color: #fff; }

.nr-glass-btn--ghost .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: linear-gradient(135deg, #0f2040 0%, #17335a 50%, #132a4a 100%);
  border: 1px solid rgba(59, 130, 246, 0.18); border-radius: inherit; transition: all 0.3s;
}
.nr-glass-btn--ghost { color: #c8d8f0; }
.nr-glass-btn--ghost:hover { color: #e0eaff; }
.nr-glass-btn--ghost:hover .nr-glass-btn-bg { background: linear-gradient(135deg, #162d50 0%, #1e4976 50%, #1a3f66 100%); border-color: rgba(59, 130, 246, 0.3); }

.nr-glass-btn--danger .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: linear-gradient(135deg, #ef4444, #dc2626);
  border-radius: inherit; transition: opacity 0.3s;
}
.nr-glass-btn--danger { color: white; box-shadow: 0 4px 20px rgba(239,68,68,0.3); }

.nr-glass-btn-content { position: relative; z-index: 2; display: flex; align-items: center; gap: inherit; }
.nr-glass-btn-spinner { display: flex; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.nr-glass-btn-icon { display: flex; font-size: 1.1em; }
.nr-glass-btn-label { white-space: nowrap; }

.nr-glass-btn.is-loading { opacity: 0.8; pointer-events: none; }
.nr-glass-btn.is-disabled { opacity: 0.4; pointer-events: none; cursor: not-allowed; }
</style>

<!-- ─── 浅色主题覆盖 ───
  注意：不能写进 scoped 样式块再包 :global()。@vue/compiler-sfc 3.5.x 会把
  `:global([data-theme='light']) .nr-glass-btn--ghost ...` 编译成只有
  `[data-theme='light'] ` 的退化选择器（括号外的类选择器被丢弃），浅色样式会
  打到 html[data-theme=light] 上，按钮本体仍是深蓝玻璃底。
  必须放在普通 style 块里写完整选择器（GlassButtonLightTheme.test.ts 钉住编译产物）。 -->
<style>
[data-theme='light'] .nr-glass-btn--secondary .nr-glass-btn-bg {
  background: var(--nr-bg-surface);
  border: 1px solid var(--nr-glass-border-hover);
}
[data-theme='light'] .nr-glass-btn--secondary {
  color: var(--nr-text-secondary);
  box-shadow: var(--nr-shadow-sm);
}
[data-theme='light'] .nr-glass-btn--secondary:hover .nr-glass-btn-bg {
  background: var(--nr-bg-elevated);
  border-color: var(--nr-primary-soft-border);
}
[data-theme='light'] .nr-glass-btn--secondary:hover { color: var(--nr-text-primary); }

[data-theme='light'] .nr-glass-btn--ghost .nr-glass-btn-bg {
  background: transparent;
  border: 1px solid var(--nr-glass-border);
}
[data-theme='light'] .nr-glass-btn--ghost { color: var(--nr-text-secondary); box-shadow: none; }
[data-theme='light'] .nr-glass-btn--ghost:hover .nr-glass-btn-bg {
  background: var(--nr-glass-bg);
  border-color: var(--nr-glass-border-hover);
}
[data-theme='light'] .nr-glass-btn--ghost:hover { color: var(--nr-text-primary); }
</style>
