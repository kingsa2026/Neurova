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
  height: 40px;
  width: auto;
  max-width: 170px;
  object-fit: contain;
  flex-shrink: 0;
  transition: all var(--nr-transition-fast);
}
/* 折叠态仅显示罗盘图形：原图 350×90 中图形占 x∈[0,94]（canvas 实测），
   34×32 cover 盒左对齐裁出完整图形（可见宽 95.6px ≥ 94 含右缘横杆） */
.nr-brand-logo-img.is-collapsed {
  width: 34px;
  height: 32px;
  max-width: none;
  object-fit: cover;
  object-position: left center;
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