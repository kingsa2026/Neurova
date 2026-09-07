<script setup lang="ts">
/**
 * 顶入卡片 — 会话页 composer 内嵌的消息队列（DeepSeek 截图形态对齐）。
 *
 * 流式中「追加对话（顶入）」：排队消息以卡片列于发送窗口顶部，每张卡片：
 * 把手（拖拽排序）/ 摘要文本 / 「↑ 立即」（插队续发）/ ✎（重新编辑，父级回填
 * textarea）/ 🗑（取消顶入）；failed 附 ↻ 重试，sending 锁定无动作。
 * remove/retry/reorder 直接走 store；send-now（需父级 drain 续发）与
 * edit（需父级把文本回填 composer）emit 给父级。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessageQueueStore, type QueuedMessage } from '@/stores/messageQueue'

const props = defineProps<{ editingQueuedId: string | null }>()

const emit = defineEmits<{
  (e: 'send-now', id: string): void
  (e: 'edit', item: QueuedMessage): void
}>()

const { t } = useI18n()
const queue = useMessageQueueStore()

const dragId = ref<string | null>(null)

function onDragStart(id: string): void {
  dragId.value = id
}

function onDrop(targetId: string): void {
  const from = dragId.value
  dragId.value = null
  if (!from || from === targetId) return
  // reorder 只吃 pending 全序：把拖动项插到目标项当前位
  const pendingIds = queue.items.filter((i) => i.status === 'pending').map((i) => i.id)
  const fromIdx = pendingIds.indexOf(from)
  const toIdx = pendingIds.indexOf(targetId)
  if (fromIdx < 0 || toIdx < 0) return
  pendingIds.splice(toIdx, 0, ...pendingIds.splice(fromIdx, 1))
  queue.reorder(pendingIds)
}
</script>

<template>
  <div v-if="queue.items.length > 0" class="nr-queue-cards" role="list">
    <div
      v-for="qi in queue.items"
      :key="qi.id"
      class="nr-queue-card"
      :class="{
        'is-editing': props.editingQueuedId === qi.id,
        'is-dragging': dragId === qi.id,
        'is-failed': qi.status === 'failed',
      }"
      role="listitem"
      :draggable="qi.status === 'pending'"
      @dragstart="onDragStart(qi.id)"
      @dragover.prevent
      @drop="onDrop(qi.id)"
      @dragend="dragId = null"
    >
      <span class="nr-queue-drag" :title="t('chat.queueDrag')">
        <svg viewBox="0 0 24 24" fill="currentColor" stroke="none">
          <circle cx="9" cy="6" r="1.5" /><circle cx="15" cy="6" r="1.5" />
          <circle cx="9" cy="12" r="1.5" /><circle cx="15" cy="12" r="1.5" />
          <circle cx="9" cy="18" r="1.5" /><circle cx="15" cy="18" r="1.5" />
        </svg>
      </span>
      <span class="nr-queue-card-text" :title="qi.status === 'failed' && qi.error ? qi.error : qi.text">
        {{ qi.text }}
      </span>
      <span v-if="qi.status === 'sending'" class="nr-queue-card-status is-sending">{{ t('chat.queueSending') }}</span>
      <span v-else-if="qi.status === 'failed'" class="nr-queue-card-status is-failed">{{ t('chat.queueFailed') }}</span>
      <template v-if="qi.status === 'pending'">
        <button class="nr-queue-now" :title="t('chat.queueSendNowTitle')" @click="emit('send-now', qi.id)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
          <span>{{ t('chat.queueSendNow') }}</span>
        </button>
        <button class="nr-queue-ico" :title="t('common.edit')" @click="emit('edit', qi)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /></svg>
        </button>
      </template>
      <button
        v-if="qi.status === 'failed'"
        class="nr-queue-retry"
        :title="t('chat.retry')"
        @click="queue.retry(qi.id); emit('send-now', qi.id)"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" /></svg>
      </button>
      <button v-if="qi.status !== 'sending'" class="nr-queue-ico" :title="t('common.delete')" @click="queue.remove(qi.id)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.nr-queue-cards {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0 0 8px;
}

.nr-queue-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-inset-deep, rgba(0, 0, 0, 0.22));
  font-size: 13px;
}

.nr-queue-card.is-editing {
  border-color: var(--nr-primary);
}

.nr-queue-card.is-failed {
  border-color: rgba(239, 68, 68, 0.45);
}

.nr-queue-card.is-dragging {
  opacity: 0.4;
}

.nr-queue-drag {
  display: flex;
  align-items: center;
  color: var(--nr-text-tertiary);
  cursor: grab;
  flex: none;
}

.nr-queue-drag svg {
  width: 14px;
  height: 14px;
}

.nr-queue-card-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--nr-text-primary);
  font-weight: 500;
}

.nr-queue-card-status {
  flex: none;
  font-size: 11px;
}

.nr-queue-card-status.is-sending {
  color: #6366f1;
}

.nr-queue-card-status.is-failed {
  color: #ef4444;
}

.nr-queue-now {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid rgba(245, 158, 11, 0.55);
  color: #f59e0b;
  background: transparent;
  border-radius: 8px;
  padding: 2px 10px;
  font-size: 12px;
  line-height: 1.6;
  cursor: pointer;
  white-space: nowrap;
}

.nr-queue-now:hover {
  background: rgba(245, 158, 11, 0.12);
}

.nr-queue-now svg {
  width: 12px;
  height: 12px;
}

.nr-queue-ico,
.nr-queue-retry {
  flex: none;
  display: flex;
  align-items: center;
  border: none;
  background: none;
  color: var(--nr-text-tertiary);
  cursor: pointer;
  padding: 2px;
}

.nr-queue-ico:hover,
.nr-queue-retry:hover {
  color: var(--nr-text-primary);
}

.nr-queue-ico svg,
.nr-queue-retry svg {
  width: 15px;
  height: 15px;
}
</style>
