<template>
  <aside class="nr-chat-sidebar" :class="{ collapsed: sidebarCollapsed }">
    <div class="nr-sidebar-header">
      <GlassButton variant="primary" size="md" style="flex: 1" @click="createSession">
        + {{ t('chat.newChat') }}
      </GlassButton>
    </div>

    <div class="nr-sidebar-search">
      <GlassInput
        v-model:model-value="searchQuery"
        :placeholder="t('common.search')"
        @update:model-value="searchQuery = $event"
      />
      <button class="nr-msg-search-open" :title="t('chat.searchInSession')" @click="$emit('openMsgSearch')"><UiIcon name="search" :size="14" /></button>
      <button class="nr-msg-search-open" :title="t('chat.crossSearchTitle')" @click="$emit('crossSearch')"><UiIcon name="globe" :size="14" /></button>
    </div>

    <div class="nr-session-list">
      <template v-for="group in groupedSessions" :key="group.key">
        <div v-if="group.label" class="nr-session-group-label">{{ group.label }}</div>
        <div
          v-for="session in group.sessions"
          :key="session.id"
          class="nr-session-item"
          :class="{ active: session.id === currentSessionId, 'drop-target': dragOverSessionId === session.id }"
          draggable="true"
          @click="$emit('switch', session.id)"
          @dragstart="onSessionDragStart(session.id, $event)"
          @dragover.prevent="dragOverSessionId = session.id"
          @dragleave="dragOverSessionId = null"
          @drop.prevent="onSessionDrop(session.id)"
        >
          <span class="nr-session-icon"><UiIcon name="chat" :size="14" /></span>
          <span class="nr-session-name">{{ session.title }}</span>
          <a-dropdown :trigger="['click']" :get-popup-container="getPopupContainer" @click.stop>
            <span class="nr-session-menu-btn" @click.stop>⋯</span>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="renameSession(session.id)">
                  {{ t('chat.rename') }}
                </a-menu-item>
                <a-menu-item @click="togglePin(session)">
                  {{ session.pinned ? t('chat.unpin') : t('chat.pin') }}
                </a-menu-item>
                <a-menu-item @click="archiveSession(session.id)">
                  {{ t('chat.archive') }}
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </template>
      <div v-if="filteredSessions.length === 0" class="nr-session-empty">
        {{ t('chat.noSessions') }}
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
// 菜单弹层挂 body：dock/侧栏容器 overflow:hidden 会挤压弹层宽度（文字竖排）
const getPopupContainer = (trigger: HTMLElement) => document.body
/**
 * 左侧会话侧栏（chat 布局模式）：模板原样迁自 ChatPage（2026-09-08 拆分）。
 * 会话分组/拖拽重排/置顶/存档走 useSessionOps；switchSession 与流式状态机
 * 耦合，emit 上抛由页面编排；页内搜索/跨会话搜索为页面级 UI，emit 触发。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useAppStore } from '@/stores/app'
import { useChatStore } from '@/stores/chat'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'
import { useSessionOps } from '@/composables/useSessionOps'
import UiIcon from '@/components/UiIcon.vue'

defineEmits<{
  switch: [sessionId: string]
  openMsgSearch: []
  crossSearch: []
}>()

const { t } = useI18n()
const appStore = useAppStore()
const chatStore = useChatStore()
const { searchQuery, filteredSessions, currentSessionId } = storeToRefs(chatStore)
const sidebarCollapsed = computed(() => appStore.sidebarCollapsed)

const {
  groupedSessions,
  dragOverSessionId,
  onSessionDragStart,
  onSessionDrop,
  createSession,
  renameSession,
  togglePin,
  archiveSession,
} = useSessionOps()
</script>

<style scoped>
.nr-chat-sidebar {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-inset);
  transition: width 0.3s ease, min-width 0.3s ease;
}
.nr-chat-sidebar.collapsed {
  width: 0;
  min-width: 0;
  overflow: hidden;
  border-right: none;
}
.nr-sidebar-header {
  display: flex;
  gap: 8px;
  padding: 16px;
}
.nr-sidebar-search {
  padding: 0 16px 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.nr-sidebar-search :deep(.nr-input) {
  flex: 1;
  min-width: 0;
}
.nr-session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}
.nr-session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 2px;
}
.nr-session-item:hover {
  background: var(--nr-glass-bg-hover);
}
.nr-session-item.active {
  background: var(--nr-primary-soft);
  border: 1px solid var(--nr-primary-soft-border);
}
.nr-session-icon {
  font-size: 16px;
  flex-shrink: 0;
}
.nr-session-name {
  flex: 1;
  font-size: 13px;
  color: var(--nr-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nr-session-menu-btn {
  color: var(--nr-text-muted);
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
}
.nr-session-item:hover .nr-session-menu-btn {
  opacity: 1;
}
.nr-session-empty {
  text-align: center;
  color: var(--nr-text-muted);
  padding: 32px 16px;
  font-size: 13px;
}
.nr-session-group-label {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 8px 6px 2px;
  user-select: none;
}
.nr-session-item.drop-target {
  border-top: 2px solid #6366f1;
}
.nr-msg-search-open {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
}
</style>
