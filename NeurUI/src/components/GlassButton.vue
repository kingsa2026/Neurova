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
/* iOS 系统按钮：Accent 蓝主按钮 / SystemGray 次按钮 / 纯文本 Ghost / 红色危险 */
.nr-glass-btn {
  position: relative; display: inline-flex; align-items: center; justify-content: center;
  border: none; cursor: pointer; overflow: hidden;
  /* 本体必须显式透明：UA 的 button 默认 ButtonFace 不透明（Windows 浅灰 #f0f0f0），
     会透过 secondary 的 3.5% 玻璃层变白胶囊；背景一律由 .nr-glass-btn-bg 承担 */
  background: transparent;
  border-radius: 12px; font-family: var(--nr-font-body);
  font-weight: 500; letter-spacing: -0.01em;
  transition: transform 0.15s cubic-bezier(0.32, 0.72, 0, 1), box-shadow 0.25s, opacity 0.25s, background 0.25s;
  outline: none;
  -webkit-tap-highlight-color: transparent;
}
.nr-glass-btn:active { transform: scale(0.97); }
.nr-glass-btn--sm { height: 30px; padding: 0 14px; font-size: 12px; border-radius: 9px; gap: 6px; }
.nr-glass-btn--md { height: 38px; padding: 0 20px; font-size: 13px; border-radius: 12px; gap: 8px; }
.nr-glass-btn--lg { height: 46px; padding: 0 28px; font-size: 15px; border-radius: 14px; gap: 10px; }

/* Primary: iOS Accent 蓝（竖向微渐变还原系统按钮光泽） */
.nr-glass-btn--primary .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: var(--nr-gradient-primary);
  transition: opacity 0.3s;
}
.nr-glass-btn--primary {
  color: #fff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.18), 0 2px 12px rgba(10, 132, 255, 0.32);
}
.nr-glass-btn--primary:hover .nr-glass-btn-bg { opacity: 0.92; }

/* Secondary: iOS SystemFill 灰按钮 */
.nr-glass-btn--secondary .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border); border-radius: inherit;
  transition: all 0.3s;
}
.nr-glass-btn--secondary {
  color: var(--nr-text-primary);
  box-shadow: inset 0 0.5px 0 rgba(var(--nr-glass-rgb), 0.1);
}
.nr-glass-btn--secondary:hover .nr-glass-btn-bg { background: var(--nr-glass-bg-hover); border-color: var(--nr-glass-border-hover); }

/* Ghost: iOS 纯文本蓝按钮 */
.nr-glass-btn--ghost .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: transparent;
  border: 1px solid transparent; border-radius: inherit; transition: all 0.3s;
}
.nr-glass-btn--ghost { color: var(--nr-primary-light); }
.nr-glass-btn--ghost:hover { color: var(--nr-primary-light); }
.nr-glass-btn--ghost:hover .nr-glass-btn-bg { background: var(--nr-primary-soft); border-color: var(--nr-primary-soft-border); }

/* Danger: iOS 红色 */
.nr-glass-btn--danger .nr-glass-btn-bg {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, #ff5f52 0%, var(--nr-error) 60%, #e3372c 100%);
  border-radius: inherit; transition: opacity 0.3s;
}
.nr-glass-btn--danger {
  color: #fff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 2px 12px rgba(255, 69, 58, 0.3);
}
.nr-glass-btn--danger:hover .nr-glass-btn-bg { opacity: 0.92; }

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
  color: var(--nr-text-primary);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
[data-theme='light'] .nr-glass-btn--secondary:hover .nr-glass-btn-bg {
  background: var(--nr-bg-elevated);
  border-color: var(--nr-primary-soft-border);
}
[data-theme='light'] .nr-glass-btn--secondary:hover { color: var(--nr-text-primary); }

[data-theme='light'] .nr-glass-btn--ghost .nr-glass-btn-bg {
  background: transparent;
  border: 1px solid transparent;
}
[data-theme='light'] .nr-glass-btn--ghost { color: var(--nr-primary); box-shadow: none; }
[data-theme='light'] .nr-glass-btn--ghost:hover .nr-glass-btn-bg {
  background: var(--nr-primary-soft);
  border-color: var(--nr-primary-soft-border);
}
[data-theme='light'] .nr-glass-btn--ghost:hover { color: var(--nr-primary); }
</style>