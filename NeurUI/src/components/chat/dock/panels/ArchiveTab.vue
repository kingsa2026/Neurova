<template>
  <div class="nr-dock-archive">
    <div class="nr-dock-archive-header">
      <span class="nr-dock-archive-title">{{ t('chat.archivedSessions') }}</span>
    </div>
    <div class="nr-dock-archive-list">
      <div v-for="session in archivedSessions" :key="session.id" class="nr-session-item archived">
        <span class="nr-session-icon"><UiIcon name="archive" :size="14" /></span>
        <span class="nr-session-name">{{ session.title }}</span>
        <button class="nr-archived-restore-btn" @click="restoreArchivedSession(session.id)">
          {{ t('chat.restore') }}
        </button>
      </div>
      <div v-if="archivedSessions.length === 0" class="nr-session-empty">{{ t('chat.noArchivedSessions') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * dock 存档会话 tab：迁自 ChatPage 存档面板（行为等价）。
 * 打开时加载存档列表；恢复后列表由 chatStore 刷新。
 */
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useSessionOps } from '@/composables/useSessionOps'
import UiIcon from '@/components/UiIcon.vue'

const { t } = useI18n()
const chatStore = useChatStore()
const { archivedSessions } = storeToRefs(chatStore)
const { restoreArchivedSession, loadArchivedSessions } = useSessionOps()

onMounted(() => {
  void loadArchivedSessions()
})
</script>

<style scoped>
.nr-dock-archive {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px;
  gap: 8px;
}
.nr-dock-archive-header {
  display: flex;
  align-items: center;
}
.nr-dock-archive-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary, #e8eaf2);
}
.nr-dock-archive-list {
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
  color: var(--nr-text-secondary, #8b8fa3);
  font-size: 13px;
}
.nr-session-item.archived {
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.03));
  margin-bottom: 4px;
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
.nr-archived-restore-btn {
  flex: none;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.12));
  background: transparent;
  color: var(--nr-text-primary, #e8eaf2);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}
.nr-archived-restore-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}
.nr-session-empty {
  padding: 24px 0;
  text-align: center;
  color: var(--nr-text-secondary, #8b8fa3);
  font-size: 12px;
}
</style>
