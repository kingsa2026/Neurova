<template>
  <nav class="nr-glass-nav" :class="{ 'is-collapsed': collapsed }">
    <div class="nr-glass-nav-backdrop" />
    <div class="nr-glass-nav-content">
      <div class="nr-glass-nav-brand" @click="$emit('brand-click')">
        <slot name="brand">
          <img src="/img/NEUROVA-LOGO350white.png" alt="Neurova" class="nr-glass-nav-logo-img" :class="{ 'is-collapsed': collapsed }" />
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
withDefaults(defineProps<{
  collapsed?: boolean
}>(), { collapsed: false })

defineEmits<{ 'brand-click': [] }>()
</script>

<style scoped>
.nr-glass-nav {
  position: relative; display: flex; flex-direction: column;
  width: var(--nr-sidebar-w); height: 100vh;
  transition: width 0.35s cubic-bezier(0.22, 1, 0.36, 1);
  z-index: 10;
}
.nr-glass-nav.is-collapsed { width: var(--nr-sidebar-collapsed-w); }
.nr-glass-nav-backdrop {
  position: absolute; inset: 0; z-index: 0;
  background: rgba(10, 14, 26, 0.7);
  backdrop-filter: blur(40px) saturate(180%);
  border-right: 1px solid var(--nr-glass-border);
}
.nr-glass-nav-content {
  position: relative; z-index: 1; display: flex; flex-direction: column;
  padding: 16px 12px; height: 100%; overflow-y: auto; overflow-x: hidden;
}
.nr-glass-nav-brand {
  display: flex; align-items: center; gap: 10px; padding: 8px 10px;
  margin-bottom: 16px; cursor: pointer; border-radius: 10px;
  transition: background 0.2s;
}
.nr-glass-nav-brand:hover { background: rgba(255,255,255,0.04); }
.nr-glass-nav-logo-img {
  height: 32px; width: auto; max-width: 140px;
  object-fit: contain; flex-shrink: 0;
  transition: all 0.3s ease;
}
.nr-glass-nav-logo-img.is-collapsed {
  height: 28px; max-width: 28px; object-fit: contain;
}
.nr-glass-nav-items { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.nr-glass-nav-footer { margin-top: auto; padding-top: 12px; border-top: 1px solid var(--nr-glass-border); }
</style>
