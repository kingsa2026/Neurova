<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listNotifications, markNotificationRead, markAllNotificationsRead, type NotificationItem } from '@/api/misc'

const items = ref<NotificationItem[]>([])
const loading = ref(true)
const error = ref('')

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await listNotifications()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function markRead(item: NotificationItem) {
  if (item.read) return
  try {
    await markNotificationRead(item.id)
    item.read = true
  } catch {
    // 已读失败不阻塞列表
  }
}

async function markAll() {
  try {
    await markAllNotificationsRead()
    await load()
  } catch {
    // 忽略
  }
}
</script>

<template>
  <div>
    <div class="head-row">
      <h2 class="page-title">通知</h2>
      <button class="ghost" @click="markAll">全部已读</button>
    </div>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error-text">{{ error }}</p>
    <p v-else-if="!items.length" class="muted">暂无通知</p>
    <div v-for="n in items" :key="n.id" class="card notif" :class="{ unread: !n.read }" @click="markRead(n)">
      <div class="notif-head">
        <span class="notif-title">{{ n.title || '通知' }}</span>
        <span v-if="!n.read" class="dot" />
      </div>
      <div class="muted notif-body">{{ n.content || n.message }}</div>
      <div class="muted notif-time">{{ n.created_at ?? '' }}</div>
    </div>
  </div>
</template>

<style scoped>
.head-row { display: flex; justify-content: space-between; align-items: center; }
.page-title { font-size: 18px; margin: 4px 0 14px; }
.ghost {
  background: var(--bg-card); border: 1px solid var(--border); color: var(--text-dim);
  border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
.notif.unread { border-color: var(--primary-dim); }
.notif-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.notif-title { font-weight: 600; font-size: 14px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--primary); }
.notif-body { font-size: 13px; white-space: pre-wrap; }
.notif-time { margin-top: 6px; font-size: 11px; }
</style>
