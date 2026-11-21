<template>
  <div class="nr-dock-history">
    <div class="nr-dock-history-actions">
      <GlassButton variant="primary" size="sm" @click="createSession">+ {{ t('chat.newChat') }}</GlassButton>
      <GlassButton
        variant="ghost"
        size="sm"
        :title="t('chat.archivedSessions')"
        @click="onOpenArchive"
      >
        <UiIcon name="archive" :size="14" />
      </GlassButton>
      <GlassButton variant="ghost" size="sm" :title="t('chat.crossSearchTitle')" @click="$emit('crossSearch')"><UiIcon name="globe" :size="14" /></GlassButton>
    </div>
    <div class="nr-dock-history-search">
      <GlassInput
        v-model:model-value="searchQuery"
        :placeholder="t('common.search')"
        @update:model-value="searchQuery = $event"
      />
    </div>
    <div class="nr-dock-history-list">
      <div
        v-for="session in visibleSessions"
        :key="session.id"
        class="nr-session-item"
        :class="{ active: session.id === currentSessionId }"
        @click="$emit('switch', session.id)"
      >
        <span class="nr-session-icon"><UiIcon name="chat" :size="14" /></span>
        <span class="nr-session-name">{{ session.title }}</span>
        <a-dropdown :trigger="['click']" :get-popup-container="overlayContainerToBody" @click.stop>
          <span class="nr-session-menu-btn" @click.stop>⋯</span>
          <template #overlay>
            <a-menu>
              <a-menu-item @click="renameSession(session.id)">{{ t('chat.rename') }}</a-menu-item>
              <a-menu-item @click="togglePin(session)">{{ session.pinned ? t('chat.unpin') : t('chat.pin') }}</a-menu-item>
              <a-menu-item @click="archiveSession(session.id)">{{ t('chat.archive') }}</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>
      <!-- E3 勘察同因同修：dock 历史列表与侧栏同一渲染窗口策略 -->
      <button
        v-if="hiddenSessionCount > 0"
        class="nr-session-load-more"
        type="button"
        @click="loadMoreSessions"
      >
        {{ t('chat.loadMoreSessions', { count: hiddenSessionCount }) }}
      </button>
      <div v-if="filteredSessions.length === 0" class="nr-session-empty">{{ t('chat.noSessions') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 菜单弹层挂 body：dock/侧栏容器 overflow:hidden 会挤压弹层宽度（文字竖排）
/**
 * dock 历史会话 tab：迁自 ChatPage 右侧历史面板（行为等价）。
 * switchSession 与流式状态机耦合（abort/草稿/滚动锚定），emit 上抛由页面编排。
 */
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useRightDockStore } from '@/stores/rightDock'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'
import { useSessionOps } from '@/composables/useSessionOps'
import { useRenderWindow, LIST_RENDER_BATCH } from '@/composables/useRenderWindow'
import UiIcon from '@/components/UiIcon.vue'
import { overlayContainerToBody } from '@/utils/overlay'

defineEmits<{
  switch: [sessionId: string]
  crossSearch: []
}>()

const { t } = useI18n()
const chatStore = useChatStore()
const rightDock = useRightDockStore()
const { searchQuery, filteredSessions, currentSessionId } = storeToRefs(chatStore)
const { createSession, renameSession, togglePin, archiveSession, loadArchivedSessions } = useSessionOps()

// E3 勘察同因同修：与 ChatSessionSidebar 同一渲染窗口策略（首屏 50 条，
// 加载更多按批放量；整表重载时窗口归位）。
const {
  visibleItems: visibleSessions,
  hiddenCount: hiddenSessionCount,
  loadMore: loadMoreSessions,
} = useRenderWindow(filteredSessions, {
  batch: LIST_RENDER_BATCH,
  resetKey: () => chatStore.sessions,
})

/** 打开存档 tab（原页头历史面板「🗂 存档会话」按钮等价行为：打开即加载列表） */
function onOpenArchive(): void {
  rightDock.openArchive()
  void loadArchivedSessions()
}
</script>

<style scoped>
.nr-dock-history {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px;
  gap: 8px;
}
.nr-dock-history-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.nr-dock-history-actions :first-child {
  flex: 1;
}
.nr-dock-history-search {
  display: flex;
  gap: 6px;
}
.nr-dock-history-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nr-session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--nr-text-secondary, #8b8fa3);
  font-size: 13px;
}
.nr-session-item:hover {
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.06));
}
.nr-session-item.active {
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.08));
  color: var(--nr-text-primary, #e8eaf2);
}
.nr-session-icon {
  flex: none;
}
.nr-session-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-session-menu-btn {
  flex: none;
  opacity: 0.4;
  padding: 2px 6px;
  border-radius: 4px;
}
.nr-session-menu-btn:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.1);
}
.nr-session-empty {
  padding: 24px 0;
  text-align: center;
  color: var(--nr-text-secondary, #8b8fa3);
  font-size: 12px;
}
/* E3：加载更多入口（与侧栏同款，颜色全走既有令牌） */
.nr-session-load-more {
  display: block;
  margin: 8px auto;
  padding: 5px 12px;
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}
.nr-session-load-more:hover {
  background: var(--nr-glass-bg-hover);
  color: var(--nr-text-primary);
}
</style>
