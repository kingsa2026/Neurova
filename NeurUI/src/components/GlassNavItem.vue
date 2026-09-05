<template>
  <router-link v-if="to" :to="to" class="nr-nav-item" :class="{ 'is-active': isActive, 'is-collapsed': collapsed }">
    <span class="nr-nav-item-icon"><slot name="icon" /></span>
    <span v-if="!collapsed" class="nr-nav-item-label">{{ label }}</span>
    <span v-if="badge && !collapsed" class="nr-nav-item-badge">{{ badge }}</span>
  </router-link>
  <div v-else class="nr-nav-item nr-nav-item--button" :class="{ 'is-active': isActive, 'is-collapsed': collapsed }" @click="$emit('click')">
    <span class="nr-nav-item-icon"><slot name="icon" /></span>
    <span v-if="!collapsed" class="nr-nav-item-label">{{ label }}</span>
    <span v-if="badge && !collapsed" class="nr-nav-item-badge">{{ badge }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const props = withDefaults(defineProps<{
  to?: string
  label: string
  badge?: string | number
  collapsed?: boolean
  activePath?: string
}>(), { collapsed: false })

defineEmits<{ click: [] }>()

const route = useRoute()
const isActive = computed(() => {
  if (props.activePath) return route.path.startsWith(props.activePath)
  if (props.to) return route.path === props.to || route.path.startsWith(props.to + '/')
  return false
})
</script>

<style scoped>
/* iOS 导航项：胶囊选中态（Accent 蓝填充，无左侧指示条） */
.nr-nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 12px;
  color: var(--nr-text-secondary); text-decoration: none;
  transition: all 0.2s cubic-bezier(0.32, 0.72, 0, 1); cursor: pointer; position: relative;
  font-size: 14px; font-weight: 450; letter-spacing: -0.01em;
}
.nr-nav-item:hover { color: var(--nr-text-primary); background: var(--nr-glass-bg); }
.nr-nav-item.is-active {
  color: var(--nr-primary-light); background: var(--nr-primary-soft);
  font-weight: 600;
}
.nr-nav-item.is-active:hover {
  background: var(--nr-primary-soft);
}
.nr-nav-item.is-collapsed { justify-content: center; padding: 11px; }
.nr-nav-item-icon { display: flex; align-items: center; font-size: 19px; flex-shrink: 0; width: 22px; justify-content: center; }
.nr-nav-item-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nr-nav-item-badge {
  margin-left: auto; font-size: 10px; font-weight: 600;
  background: var(--nr-primary); color: #fff; padding: 1px 6px;
  border-radius: 10px; min-width: 18px; text-align: center;
}
</style>
