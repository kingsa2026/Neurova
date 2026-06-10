<template>
  <div class="notification-page">
    <div class="page-header">
      <h2 class="page-title">
        {{ t('system.notifications') }}
        <a-badge :count="unreadCount" :offset="[8, -4]" />
      </h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="markingAll" @click="markAllRead">{{ t('common.all') }} Read</GlassButton>
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchNotifications">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <!-- Notification list -->
    <a-spin :spinning="loading">
      <div class="notification-list">
        <GlassPanel
          v-for="notif in notifications"
          :key="notif.id"
          :variant="notif.read ? 'subtle' : 'default'"
          class="notification-item"
          :class="{ unread: !notif.read }"
        >
          <div class="notif-content">
            <div class="notif-header">
              <span class="notif-title">{{ notif.title }}</span>
              <span class="notif-time">{{ formatTime(notif.created_at) }}</span>
            </div>
            <p class="notif-body">{{ notif.message }}</p>
            <div class="notif-meta">
              <a-tag v-if="notif.type" :color="typeColor(notif.type)" size="small">{{ notif.type }}</a-tag>
              <div class="notif-actions">
                <GlassButton v-if="!notif.read" variant="ghost" size="sm" @click="markRead(notif.id)">
                  Mark Read
                </GlassButton>
                <GlassButton variant="ghost" size="sm" @click="deleteNotif(notif.id)">
                  {{ t('common.delete') }}
                </GlassButton>
              </div>
            </div>
          </div>
        </GlassPanel>
        <a-empty v-if="!notifications.length && !loading" :description="t('common.noData')" />
      </div>
    </a-spin>

    <!-- Pagination -->
    <div v-if="total > pageSize" class="pagination-row">
      <a-pagination v-model:current="page" :total="total" :page-size="pageSize" @change="onPageChange" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const markingAll = ref(false)
const notifications = ref<any[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const unreadCount = computed(() => notifications.value.filter(n => !n.read).length)

const typeColor = (type: string) => {
  const map: Record<string, string> = { info: 'blue', warning: 'orange', error: 'red', success: 'green' }
  return map[type] || 'default'
}

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const fetchNotifications = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/notifications', { params: { page: page.value, page_size: pageSize.value } })
    const data = res?.data ?? res ?? {}
    notifications.value = data.items ?? data.notifications ?? (Array.isArray(data) ? data : [])
    total.value = data.total ?? notifications.value.length
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const markRead = async (id: string) => {
  try {
    await request.put(`/notifications/${id}/read`)
    const notif = notifications.value.find(n => n.id === id)
    if (notif) notif.read = true
  } catch {
    message.error(t('common.error'))
  }
}

const markAllRead = async () => {
  markingAll.value = true
  try {
    await request.put('/notifications/read-all')
    notifications.value.forEach(n => { n.read = true })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    markingAll.value = false
  }
}

const deleteNotif = async (id: string) => {
  try {
    await request.delete(`/notifications/${id}`)
    notifications.value = notifications.value.filter(n => n.id !== id)
    total.value = Math.max(0, total.value - 1)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

const onPageChange = (p: number) => { page.value = p; fetchNotifications() }

onMounted(fetchNotifications)
</script>

<style scoped>
.notification-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; display: flex; align-items: center; gap: 8px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }
.notification-list { display: flex; flex-direction: column; gap: 12px; }
.notification-item { transition: all 0.2s; }
.notification-item.unread { border-left: 3px solid #6366f1; }
.notif-content { display: flex; flex-direction: column; gap: 8px; }
.notif-header { display: flex; justify-content: space-between; align-items: center; }
.notif-title { font-weight: 600; color: var(--nr-text-primary); font-size: 14px; }
.notif-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.notif-body { font-size: 13px; color: var(--nr-text-secondary); margin: 0; }
.notif-meta { display: flex; justify-content: space-between; align-items: center; }
.notif-actions { display: flex; gap: 6px; }
.pagination-row { display: flex; justify-content: center; padding-top: 8px; }
</style>
