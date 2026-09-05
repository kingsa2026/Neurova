<template>
  <!-- 品牌区（侧边栏顶部 / 认证页大标）：两套皮肤统一沿用原版 NEUROVA 图片 logo，
       深色主题渲染白图、浅色主题渲染黑图 —— 深浅色由图片资源适配，与皮肤无关 -->
  <span class="nr-brand" :class="[`nr-brand--${size}`, { 'is-collapsed': collapsed }]">
    <img
      :src="appStore.isDark ? '/img/NEUROVA-LOGO350white.png' : '/img/NEUROVA-LOGO350black.png'"
      alt="Neurova"
      class="nr-brand-logo-img"
      :class="{ 'is-collapsed': collapsed }"
    />
  </span>
</template>

<script setup lang="ts">
import { useAppStore } from '@/stores/app'

withDefaults(defineProps<{
  collapsed?: boolean
  /** sm = 侧边栏紧凑形态；lg = 认证页大标（居中型） */
  size?: 'sm' | 'lg'
}>(), { collapsed: false, size: 'sm' })

const appStore = useAppStore()
</script>

<style scoped>
.nr-brand { display: inline-flex; align-items: center; }

.nr-brand-logo-img {
  height: 30px;
  width: auto;
  max-width: 140px;
  object-fit: contain;
  flex-shrink: 0;
  transition: all var(--nr-transition-fast);
}
.nr-brand-logo-img.is-collapsed {
  height: 26px;
  max-width: 26px;
}

/* ─── lg 大标（认证页）：原版图片 logo 放大并居中 ─── */
.nr-brand--lg {
  display: flex;
  justify-content: center;
  margin: 0 auto 24px;
}
.nr-brand--lg .nr-brand-logo-img {
  height: auto;
  max-width: 280px;
}
</style>