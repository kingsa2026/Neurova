<template>
  <div class="nr-star-bg" aria-hidden="true">
    <div class="nr-star-aurora" />
  </div>
</template>

<script setup lang="ts">
// iOS 氛围壁纸（Liquid Glass 时代背景）：纯 CSS 极光光晕，
// 深浅两套主题都适用（颜色由 --nr-* 令牌驱动），替代早期星空 canvas。
// 注意：App.vue 全局 .star-bg 已承担全站壁纸，本组件供登录/注册等
// 独立路由页局部复用，二者同为固定装饰层，叠加安全。
</script>

<style scoped>
.nr-star-bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.nr-star-aurora {
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse 55% 42% at 18% 12%, rgba(10, 132, 255, 0.1) 0%, transparent 62%),
    radial-gradient(ellipse 46% 38% at 82% 20%, rgba(100, 210, 255, 0.06) 0%, transparent 60%),
    radial-gradient(ellipse 60% 48% at 62% 88%, rgba(191, 90, 242, 0.05) 0%, transparent 62%),
    var(--nr-bg-deep);
}
</style>