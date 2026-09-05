<template>
  <nav class="nr-glass-nav" :class="{ 'is-collapsed': collapsed }">
    <div class="nr-glass-nav-backdrop" />
    <div class="nr-glass-nav-content">
      <div class="nr-glass-nav-brand" @click="$emit('brand-click')">
        <slot name="brand">
          <!-- 默认品牌区：皮肤感知的 BrandLogo（cosmic 图片 / ios 玻璃 N 字标） -->
          <BrandLogo :collapsed="collapsed" />
        </slot>
      </div>
      <div class="nr-glass-nav-items">
        <slot />
      </div>
      <div class="nr-glass-nav-footer">
        <slot name="footer" />
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import BrandLogo from '@/components/BrandLogo.vue'

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
}
.nr-glass-nav.is-collapsed { width: var(--nr-sidebar-collapsed-w); }
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
  padding: 16px 12px; height: 100%; overflow-y: auto; overflow-x: hidden;
}
.nr-glass-nav-brand {
  display: flex; align-items: center; gap: 10px; padding: 8px 10px;
  margin-bottom: 16px; cursor: pointer; border-radius: var(--nr-radius-md);
  transition: background 0.2s;
}
.nr-glass-nav-brand:hover { background: var(--nr-glass-bg); }
.nr-glass-nav-items { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.nr-glass-nav-footer {
  margin-top: auto; padding-top: 12px;
  border-top: 1px solid var(--nr-glass-border);
}
</style>