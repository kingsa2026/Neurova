<template>
  <button
    class="nr-theme-toggle"
    :title="appStore.isDark ? t('theme.light') : t('theme.dark')"
    :aria-label="appStore.isDark ? t('theme.light') : t('theme.dark')"
    @click="appStore.toggleTheme()"
  >
    <!-- 深色模式显示月亮（点击切浅色）；浅色模式显示太阳（点击切深色） -->
    <span class="nr-toggle-icons" :class="{ 'is-dark': appStore.isDark }">
      <svg class="nr-toggle-icon nr-toggle-icon--sun" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="12" cy="12" r="4.4" />
        <path d="M12 1.6v2.4M12 20v2.4M1.6 12h2.4M20 12h2.4M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M19.1 4.9l-1.7 1.7M6.6 17.4l-1.7 1.7" />
      </svg>
      <svg class="nr-toggle-icon nr-toggle-icon--moon" viewBox="0 0 24 24" width="18" height="18" fill="none">
        <path d="M20.6 14.2A8.7 8.7 0 0 1 9.8 3.4a8.7 8.7 0 1 0 10.8 10.8z"
          fill="currentColor" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
      </svg>
    </span>
    <!-- 玻璃高光 -->
    <span class="nr-toggle-sheen" />
  </button>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'

const { t } = useI18n()
const appStore = useAppStore()
</script>

<style scoped>
/* iOS 圆形玻璃切换钮：太阳/月亮交叉过渡 */
.nr-theme-toggle {
  position: relative;
  width: 36px; height: 36px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 50%;
  background: var(--nr-glass-bg);
  backdrop-filter: blur(var(--nr-glass-blur)) saturate(180%);
  -webkit-backdrop-filter: blur(var(--nr-glass-blur)) saturate(180%);
  color: var(--nr-text-secondary);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  transition: all 0.25s cubic-bezier(0.32, 0.72, 0, 1);
  overflow: hidden;
  box-shadow: inset 0 0.5px 0 rgba(var(--nr-glass-rgb), 0.12);
}
.nr-theme-toggle:hover {
  background: var(--nr-glass-bg-hover);
  border-color: var(--nr-glass-border-hover);
  color: var(--nr-text-primary);
}
.nr-theme-toggle:active { transform: scale(0.92); }

.nr-toggle-icons { position: relative; width: 18px; height: 18px; display: block; }
.nr-toggle-icon {
  position: absolute; inset: 0;
  transition: transform 0.45s cubic-bezier(0.34, 1.28, 0.64, 1), opacity 0.3s ease;
}
.nr-toggle-icon--sun {
  transform: rotate(0deg) scale(1);
  opacity: 1;
}
.nr-toggle-icon--moon {
  transform: rotate(-90deg) scale(0.4);
  opacity: 0;
}
/* 深色：月亮出现于左旋位；太阳隐出并旋转 */
.nr-toggle-icons.is-dark .nr-toggle-icon--sun {
  transform: rotate(90deg) scale(0.4);
  opacity: 0;
}
.nr-toggle-icons.is-dark .nr-toggle-icon--moon {
  transform: rotate(0deg) scale(1);
  opacity: 1;
}

/* 玻璃顶部高光（Liquid Glass 细节） */
.nr-toggle-sheen {
  position: absolute; inset: 0; border-radius: 50%; pointer-events: none;
  background: radial-gradient(ellipse 70% 34% at 50% 18%, rgba(var(--nr-glass-rgb), 0.16) 0%, transparent 70%);
}
</style>