<template>
  <div class="nr-page-tabs">
    <router-link
      v-for="tab in tabs"
      :key="tab.to"
      :to="tab.to"
      class="nr-page-tab"
      :class="{ 'is-active': isActive(tab.to) }"
    >
      {{ t(tab.labelKey) }}
    </router-link>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

export interface AgentPageTab {
  /** i18n 键: tab 标签 */
  labelKey: string
  /** 目标路由（成对页面各自的路径） */
  to: string
}

defineProps<{ tabs: AgentPageTab[] }>()

const route = useRoute()
const { t } = useI18n()

function isActive(to: string): boolean {
  const current = route?.path ?? ''
  return current === to || current.startsWith(to + '/')
}
</script>

<style scoped>
.nr-page-tabs {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px; margin-bottom: 16px;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  border-radius: 12px;
}

.nr-page-tab {
  padding: 6px 16px; border-radius: 9px;
  font-size: 13px; font-weight: 450;
  color: var(--nr-text-secondary); text-decoration: none;
  transition: all 0.18s ease; white-space: nowrap;
}
.nr-page-tab:hover { color: var(--nr-text-primary); background: var(--nr-glass-bg-hover); }
.nr-page-tab.is-active {
  color: var(--nr-primary-light);
  background: var(--nr-primary-soft);
  font-weight: 550;
}
</style>
