<template>
  <nav class="nr-glass-nav" :class="{ 'is-collapsed': collapsed }">
    <div class="nr-glass-nav-backdrop" />
    <div class="nr-glass-nav-content">
      <GlassSurface
        class="nr-glass-nav-brand-surface"
        width="100%"
        height="auto"
        :border-radius="27"
        :background-opacity="0.12"
        :displace="0.5"
        padding="0"
      >
        <div class="nr-glass-nav-brand" @click="$emit('brand-click')">
          <slot name="brand">
            <!-- 默认品牌区：皮肤感知的 BrandLogo（cosmic 图片 / ios 玻璃 N 字标） -->
            <BrandLogo :collapsed="collapsed" />
          </slot>
        </div>
      </GlassSurface>
      <div class="nr-glass-nav-items">
        <slot />
      </div>
      <GlassSurface
        v-if="$slots.footer"
        class="nr-glass-nav-footer-surface"
        width="100%"
        height="auto"
        :border-radius="27"
        :background-opacity="0.12"
        :displace="0.5"
        padding="0"
      >
        <div class="nr-glass-nav-footer">
          <slot name="footer" />
        </div>
      </GlassSurface>
    </div>
  </nav>
</template>

<script setup lang="ts">
import BrandLogo from '@/components/BrandLogo.vue'
import GlassSurface from '@/components/GlassSurface.vue'

withDefaults(defineProps<{
  collapsed?: boolean
}>(), { collapsed: false })

defineEmits<{ 'brand-click': [] }>()
</script>

<style scoped>
/* iOS 侧栏：Liquid Glass 材质 + 顶部高光 + Activity 分隔线 */
.nr-glass-nav {
  position: relative; display: flex; flex-direction: column;
  width: var(--nr-sidebar-w); height: 100vh;
  transition: width 0.35s cubic-bezier(0.22, 1, 0.36, 1);
  z-index: 10;
  /* 折射渗透量：菜单区上/下延伸进品牌区/底部区背后，供玻璃折射滚动文字
     （展开态 = 品牌 surface 56 + 缝 16 / 底部 surface 66 + 缝 16） */
  --nr-nav-brand-bleed: 72px;
  --nr-nav-footer-bleed: 82px;
  /* 水平内边距单源：菜单区负 margin 外扩贴右分隔栏时引用同值补偿 */
  --nr-nav-pad-x: 12px;
}
/* 折叠态胶囊正圆 48×48：品牌 32 图 + 8×2 / 底部 32 头像 + 8×2（页脚包装归零）；
   渗透量 = 48 + 缝 16 = 64 */
.nr-glass-nav.is-collapsed {
  width: var(--nr-sidebar-collapsed-w);
  --nr-nav-brand-bleed: 64px;
  --nr-nav-footer-bleed: 64px;
}
.nr-glass-nav.is-collapsed .nr-glass-nav-footer { padding: 0; }
.nr-glass-nav-backdrop {
  position: absolute; inset: 0; z-index: 0;
  background: var(--nr-sidebar-bg);
  backdrop-filter: blur(var(--nr-glass-blur)) saturate(180%);
  -webkit-backdrop-filter: blur(var(--nr-glass-blur)) saturate(180%);
  border-right: 1px solid var(--nr-glass-border);
  box-shadow: inset -1px 0 0 rgba(var(--nr-glass-rgb), 0.06);
}
.nr-glass-nav-content {
  position: relative; z-index: 1; display: flex; flex-direction: column;
  padding: 16px var(--nr-nav-pad-x); height: 100%; overflow: hidden;
}
/* 品牌区/底部区液态玻璃外壳（与登录页 GlassSurface 同参数，见 liquidGlass 契约测试）；
   悬浮于菜单文字之上（z-index 2），滚动文字从其背后穿过被折射 */
.nr-glass-nav-brand-surface {
  margin-bottom: 16px; flex-shrink: 0;
  position: relative; z-index: 2;
}
.nr-glass-nav-brand {
  display: flex; align-items: center; justify-content: center; gap: 10px; padding: 8px 10px;
  cursor: pointer; border-radius: var(--nr-radius-md);
  transition: background 0.2s;
}
/* 折叠态收窄左右内边距，让 34px 罗盘图形在 40px 可用宽内完整居中 */
.nr-glass-nav.is-collapsed .nr-glass-nav-brand { padding: 8px 3px; }
.nr-glass-nav-brand:hover { background: var(--nr-glass-bg); }
/* 滚动只发生在菜单区：品牌区/底部区脱离滚动流固定悬停（2026-09-16）；
   负 margin 上/下渗透进玻璃背后 + 等量 padding 保证首尾项初始不被遮挡 */
.nr-glass-nav-items {
  flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 2px;
  overflow-y: auto; overflow-x: hidden;
  margin-top: calc(var(--nr-nav-brand-bleed) * -1);
  padding-top: var(--nr-nav-brand-bleed);
  margin-bottom: calc(var(--nr-nav-footer-bleed) * -1);
  padding-bottom: var(--nr-nav-footer-bleed);
  /* 滚动条渲染在滚动容器右缘：右外扩越过 content 内边距，贴齐侧栏分隔栏 */
  margin-right: calc(var(--nr-nav-pad-x) * -1);
  padding-right: var(--nr-nav-pad-x);
}
.nr-glass-nav-footer-surface {
  margin-top: auto; flex-shrink: 0;
  position: relative; z-index: 2;
}
.nr-glass-nav-footer { padding: 6px 10px; }
</style>