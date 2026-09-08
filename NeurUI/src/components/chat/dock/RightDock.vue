<template>
  <aside v-if="dock.isOpen" class="nr-right-dock" :style="{ width: dock.width + 'px' }">
    <DockResizer
      :width="dock.width"
      :min="320"
      :max="maxWidth"
      @resize="dock.setWidth"
      @reset="dock.resetWidth"
    />
    <DockTabBar
      :tabs="dock.tabs"
      :active-tab-id="dock.activeTabId"
      @activate="dock.activate"
      @close="onCloseTab"
      @close-all="dock.closeAll"
    />
    <div v-if="dock.activeTab" class="nr-dock-body">
      <MdPreviewPanel v-if="dock.activeTab.kind === 'markdown'" :tab="dock.activeTab" />
      <HtmlPreviewPanel v-else-if="dock.activeTab.kind === 'html'" :tab="dock.activeTab" />
      <ImagePreviewPanel v-else-if="dock.activeTab.kind === 'image'" :tab="dock.activeTab" />
      <TextPreviewPanel v-else-if="dock.activeTab.kind === 'text'" :tab="dock.activeTab" />
      <AudioPreviewPanel v-else-if="dock.activeTab.kind === 'audio'" :tab="dock.activeTab" />
      <HistoryTab v-else-if="dock.activeTab.kind === 'history'" @switch="onSessionSwitch" @cross-search="onCrossSearch" />
      <ArchiveTab v-else-if="dock.activeTab.kind === 'archive'" />
      <ComputerTab v-else-if="dock.activeTab.kind === 'computer'" :agent-id="agentId" />
      <div v-else class="nr-dock-empty">{{ t('dock.empty') }}</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * 对话页右侧多标签 dock：产物文档 / 历史会话 / 存档 / 电脑分屏统一容器。
 *
 * 挂位：ChatPage 中 `<main class="nr-chat-main">` 之后的 flex 兄弟节点
 * （接替原 ComputerUsePanel 直挂位）；tabs 全空时整体不渲染（宽度归零）。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRightDockStore } from '@/stores/rightDock'
import DockResizer from './DockResizer.vue'
import DockTabBar from './DockTabBar.vue'
import MdPreviewPanel from './panels/MdPreviewPanel.vue'
import HtmlPreviewPanel from './panels/HtmlPreviewPanel.vue'
import ImagePreviewPanel from './panels/ImagePreviewPanel.vue'
import TextPreviewPanel from './panels/TextPreviewPanel.vue'
import AudioPreviewPanel from './panels/AudioPreviewPanel.vue'
import HistoryTab from './panels/HistoryTab.vue'
import ArchiveTab from './panels/ArchiveTab.vue'
import ComputerTab from './panels/ComputerTab.vue'

const props = defineProps<{
  agentId?: string
}>()

// 面板 → 页面的事件转发（会话切换/跨会话搜索）
const emit = defineEmits<{
  switch: [sessionId: string]
  crossSearch: []
}>()

function onSessionSwitch(sessionId: string): void {
  emit('switch', sessionId)
}

function onCrossSearch(): void {
  emit('crossSearch')
}

const { t } = useI18n()
const dock = useRightDockStore()
const maxWidth = computed(() => Math.round(window.innerWidth * 0.6))

function onCloseTab(id: string): void {
  // computer tab 关闭需同步复位分屏状态机（open=false，下次 computer_action 仍会自动开）
  if (id === 'computer') {
    window.dispatchEvent(new CustomEvent('nr-dock-computer-closed'))
  }
  dock.closeTab(id)
}
</script>

<style scoped>
.nr-right-dock {
  position: relative;
  flex: none;
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  background: var(--nr-bg-primary, rgba(18, 20, 28, 0.92));
  border-left: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  overflow: hidden;
}
.nr-dock-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.nr-dock-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--nr-text-secondary, #8b8fa3);
  font-size: 13px;
}
</style>
