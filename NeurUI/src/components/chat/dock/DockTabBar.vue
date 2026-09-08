<template>
  <div class="nr-dock-tabbar">
    <div ref="stripRef" class="nr-dock-tabstrip" @wheel.prevent="onWheel">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="nr-dock-tab"
        :class="{ 'is-active': tab.id === activeTabId }"
        :title="tab.title"
        @click="$emit('activate', tab.id)"
        @auxclick.middle.prevent="$emit('close', tab.id)"
      >
        <span v-if="tab.icon" class="nr-dock-tab-icon"><UiIcon :name="tab.icon" :size="13" /></span>
        <span class="nr-dock-tab-title">{{ tab.title }}</span>
        <span
          class="nr-dock-tab-close"
          :title="t('dock.closeTab')"
          @click.stop="$emit('close', tab.id)"
        >×</span>
      </button>
    </div>
    <button class="nr-dock-tabbar-btn" :title="t('dock.closeAll')" @click="$emit('closeAll')">✕</button>
  </div>
</template>

<script setup lang="ts">
/**
 * Dock 标签栏：横向滚动、active 态、× 关闭、中键关闭、一键全关。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DockTab } from '@/stores/rightDock'
import UiIcon from '@/components/UiIcon.vue'

defineProps<{
  tabs: DockTab[]
  activeTabId: string
}>()

defineEmits<{
  activate: [id: string]
  close: [id: string]
  closeAll: []
}>()

const { t } = useI18n()
const stripRef = ref<HTMLElement | null>(null)

function onWheel(e: WheelEvent): void {
  stripRef.value?.scrollBy({ left: e.deltaY, behavior: 'smooth' })
}
</script>

<style scoped>
.nr-dock-tabbar {
  display: flex;
  align-items: stretch;
  gap: 4px;
  padding: 6px 8px 0;
  border-bottom: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  background: var(--nr-dock-tabbar-bg, transparent);
}
.nr-dock-tabstrip {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
  flex: 1;
  min-width: 0;
}
.nr-dock-tabstrip::-webkit-scrollbar {
  display: none;
}
.nr-dock-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--nr-text-secondary, #8b8fa3);
  font-size: 12px;
  max-width: 160px;
  min-width: 0;
  cursor: pointer;
  white-space: nowrap;
}
.nr-dock-tab.is-active {
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.06));
  border-color: var(--nr-border, rgba(255, 255, 255, 0.08));
  color: var(--nr-text-primary, #e8eaf2);
}
.nr-dock-tab-icon {
  flex: none;
}
.nr-dock-tab-title {
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.nr-dock-tab-close {
  flex: none;
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1;
  opacity: 0.5;
}
.nr-dock-tab-close:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.12);
}
.nr-dock-tabbar-btn {
  flex: none;
  align-self: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--nr-text-secondary, #8b8fa3);
  cursor: pointer;
  font-size: 12px;
}
.nr-dock-tabbar-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--nr-text-primary, #e8eaf2);
}
</style>
